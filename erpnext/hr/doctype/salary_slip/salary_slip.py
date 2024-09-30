# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe, erpnext
import datetime, math

from frappe.utils import add_days, cint, cstr, flt, getdate, rounded, date_diff, money_in_words
from frappe.model.naming import make_autoname

from frappe import msgprint, _, scrub
from erpnext.hr.doctype.payroll_entry.payroll_entry import get_start_end_dates
from erpnext.hr.doctype.employee.employee import get_holiday_list_for_employee
from erpnext.utilities.transaction_base import TransactionBase
from frappe.utils.background_jobs import enqueue
from erpnext.hr.doctype.additional_salary.additional_salary import get_additional_salary_component
from erpnext.hr.doctype.salary_structure_assignment.salary_structure_assignment import get_salary_structure_assignment
from erpnext.hr.doctype.income_tax_slab.income_tax_slab import get_applicable_income_tax_slab
from erpnext.hr.doctype.payroll_period.payroll_period import get_period_factor, get_payroll_period
from erpnext.hr.doctype.employee_benefit_application.employee_benefit_application import get_benefit_component_amount
from erpnext.hr.doctype.employee_benefit_claim.employee_benefit_claim import get_benefit_claim_amount, get_last_payroll_period_benefits
from erpnext.hr.utils import get_employee_leave_policy
from erpnext.hr.doctype.department.department import get_department_cost_center


class SalarySlip(TransactionBase):
	def __init__(self, *args, **kwargs):
		super(SalarySlip, self).__init__(*args, **kwargs)
		self.series = 'Sal Slip/{0}/.###'.format(self.employee)
		self.whitelisted_globals = {
			"int": int,
			"float": float,
			"long": int,
			"round": round,
			"date": datetime.date,
			"getdate": getdate,
			"date_diff": frappe.utils.date_diff
		}

	def autoname(self):
		self.name = make_autoname(self.series)

	def before_validate_links(self):
		self.loans = []
		self.advances = []

	def validate(self):
		self.status = self.get_status()
		self.validate_dates()
		self.check_existing()
		if not self.salary_slip_based_on_timesheet:
			self.get_date_details()

		self.set_employee_details()

		if not (len(self.get("earnings")) or len(self.get("deductions"))):
			# get details from salary structure
			self.get_emp_and_leave_details()
		else:
			self.get_leave_details(lwp=self.leave_without_pay, late_days=self.late_days)

		self.calculate_net_pay()
		self.calculate_mode_of_payment()
		self.remove_zero_components()

		company_currency = erpnext.get_company_currency(self.company)
		total = self.net_pay if self.is_rounding_total_disabled() else self.rounded_total
		self.total_in_words = money_in_words(total, company_currency)

		if frappe.get_cached_value("HR Settings", None, "max_working_hours_against_timesheet"):
			max_working_hours = frappe.get_cached_value("HR Settings", None, "max_working_hours_against_timesheet")
			if self.salary_slip_based_on_timesheet and (self.total_working_hours > int(max_working_hours)):
				frappe.msgprint(_("Total working hours should not be greater than max working hours {0}").
								format(max_working_hours), alert=True)

	def before_print(self, print_settings=None):
		self.company_address_doc = erpnext.get_company_address(self)

		self.total_loan_repayment = sum([flt(d.repayment_amount) for d in self.loans])
		self.total_loan_balance = sum([flt(d.balance_amount) for d in self.loans])

		self.total_advance_repayment = sum([flt(d.allocated_amount) for d in self.advances])
		self.total_advance_balance = sum([flt(d.balance_amount) for d in self.advances])

	def on_submit(self):
		if self.net_pay < 0:
			frappe.throw(_("Net Pay cannot be less than 0"))
		else:
			self.validate_mode_of_payment()
			self.update_loans()
			self.set_status()
			self.update_status(self.name)
			self.update_salary_slip_in_additional_salary()
			if (frappe.get_cached_value("HR Settings", None, "email_salary_slip_to_employee")) and not frappe.flags.via_payroll_entry:
				self.email_salary_slip()

	def on_cancel(self):
		self.update_loans()
		self.set_status()
		self.update_status()
		self.update_salary_slip_in_additional_salary()

	def on_trash(self):
		from frappe.model.naming import revert_series_if_last
		revert_series_if_last(self.series, self.name)

	def get_status(self):
		if self.docstatus == 0:
			status = "Draft"
		elif self.docstatus == 1:
			status = "Submitted"
		elif self.docstatus == 2:
			status = "Cancelled"
		return status

	def validate_dates(self):
		if date_diff(self.end_date, self.start_date) < 0:
			frappe.throw(_("To date cannot be before From date"))

	def is_rounding_total_disabled(self):
		return cint(frappe.get_cached_value("HR Settings", None, "disable_rounded_total"))

	def check_existing(self):
		if not self.salary_slip_based_on_timesheet:
			ret_exist = frappe.db.sql("""
				select name from `tabSalary Slip`
				where start_date = %s and end_date = %s and docstatus != 2
				and employee = %s and name != %s
			""", (self.start_date, self.end_date, self.employee, self.name))
			if ret_exist:
				self.employee = ''
				frappe.throw(_("Salary Slip of employee {0} already created for this period").format(self.employee))
		else:
			for data in self.timesheets:
				if frappe.db.get_value('Timesheet', data.time_sheet, 'status') == 'Payrolled':
					frappe.throw(_("Salary Slip of employee {0} already created for time sheet {1}").format(self.employee, data.time_sheet))

	def get_date_details(self):
		if not self.end_date:
			date_details = get_start_end_dates(self.payroll_frequency, self.start_date or self.posting_date)
			self.start_date = date_details.start_date
			self.end_date = date_details.end_date

	@frappe.whitelist()
	def get_emp_and_leave_details(self):
		'''First time, load all the components from salary structure'''
		if self.employee:
			self.set("earnings", [])
			self.set("deductions", [])

			if not self.salary_slip_based_on_timesheet:
				self.get_date_details()
			self.validate_dates()
			joining_date, relieving_date = frappe.get_cached_value("Employee", self.employee,
				["date_of_joining", "relieving_date"])

			self.get_leave_details(joining_date, relieving_date)
			salary_structure = self.get_salary_structure(joining_date, relieving_date)

			if salary_structure:
				self._salary_structure_doc = frappe.get_doc('Salary Structure', salary_structure)
				self.salary_slip_based_on_timesheet = self._salary_structure_doc.salary_slip_based_on_timesheet or 0
				self.set_time_sheet()
				self.pull_sal_struct()

	def set_time_sheet(self):
		if self.salary_slip_based_on_timesheet:
			self.set("timesheets", [])
			timesheets = frappe.db.sql("""
				select *
				from `tabTimesheet`
				where employee = %(employee)s and start_date BETWEEN %(start_date)s AND %(end_date)s
				and (status = 'Submitted' or status = 'Billed')
			""", {'employee': self.employee, 'start_date': self.start_date, 'end_date': self.end_date}, as_dict=1)

			for data in timesheets:
				self.append('timesheets', {
					'time_sheet': data.name,
					'working_hours': data.total_hours
				})

	def get_salary_structure(self, joining_date, relieving_date):
		extra_condition = ""
		if self.payroll_frequency:
			extra_condition += "and ss.payroll_frequency = %(payroll_frequency)s"

		st_name = frappe.db.sql("""
			select sa.salary_structure
			from `tabSalary Structure Assignment` sa
			inner join `tabSalary Structure` ss on sa.salary_structure = ss.name
			where sa.docstatus = 1 and ss.docstatus = 1 and ss.is_active ='Yes' and sa.employee = %(employee)s
				and (sa.from_date <= %(start_date)s or sa.from_date <= %(end_date)s or sa.from_date <= %(joining_date)s)
				{0}
			order by sa.from_date desc
			limit 1
		""".format(extra_condition), {
			'employee': self.employee,
			'start_date': self.start_date,
			'end_date': self.end_date,
			'joining_date': joining_date,
			'payroll_frequency': self.payroll_frequency,
		})

		if st_name:
			self.salary_structure = st_name[0][0]
			return self.salary_structure
		else:
			self.salary_structure = None
			frappe.msgprint(_("No active or default Salary Structure found for employee {0} for the given dates")
				.format(self.employee), title=_('Salary Structure Missing'))

	def pull_sal_struct(self):
		from erpnext.hr.doctype.salary_structure.salary_structure import make_salary_slip

		if self.salary_slip_based_on_timesheet:
			self.salary_structure = self._salary_structure_doc.name
			self.hour_rate = self._salary_structure_doc.hour_rate
			self.total_working_hours = sum([d.working_hours or 0.0 for d in self.timesheets]) or 0.0
			wages_amount = self.hour_rate * self.total_working_hours

			self.add_earning_for_hourly_wages(self, self._salary_structure_doc.salary_component, wages_amount)

		make_salary_slip(self._salary_structure_doc.name, self)

	def calculate_late_days(self, holidays):
		late_days = 0

		holidays = "','".join(holidays)
		late_days = frappe.db.sql("""
			SELECT count(t1.name)
			FROM `tabAttendance` as t1
			WHERE t1.docstatus = 1
				AND t1.status = 'Present'
				AND t1.late_entry = 1
				AND ifnull(leave_application, '') = ''
				AND employee = %(employee)s
				AND attendance_date between %(st_dt)s AND %(end_dt)s
				AND attendance_date not in ('{0}')
			""".format(holidays), {"employee": self.employee, "st_dt": self.start_date, "end_dt": self.end_date})

		late_days = cint(late_days[0][0]) if late_days else 0
		return late_days

	def get_leave_details(self, joining_date=None, relieving_date=None, lwp=0, late_days=0, for_preview=0):
		if not joining_date:
			joining_date, relieving_date = frappe.get_cached_value("Employee", self.employee,
				["date_of_joining", "relieving_date"])

		working_days = date_diff(self.end_date, self.start_date) + 1
		if for_preview:
			self.total_working_days = working_days
			self.payment_days = working_days
			return

		# Working Days
		holidays = self.get_holidays_for_employee(self.start_date, self.end_date)
		if not cint(frappe.get_cached_value("HR Settings", None, "include_holidays_in_total_working_days")):
			working_days -= len(holidays)
			if working_days < 0:
				frappe.throw(_("There are more holidays than working days this month."))

		self.total_working_days = working_days

		# LWP and Late calculation
		leave_policy = get_employee_leave_policy(self.employee)
		leave_count = self.get_leave_count(holidays, working_days, joining_date, relieving_date)

		self.leave_with_pay = flt(leave_count.leave_with_pay)

		actual_lwp = flt(leave_count.leave_without_pay)
		late_leave_with_pay = flt(leave_count.late_leave_with_pay)

		self.actual_late_days = self.calculate_late_days(holidays)
		actual_late_lwp = leave_policy.get_lwp_from_late_days(self.actual_late_days) if leave_policy else 0
		actual_lwp_with_late = actual_lwp + actual_late_lwp - late_leave_with_pay
		self.actual_leave_without_pay = flt(actual_lwp_with_late)

		late_lwp = leave_policy.get_lwp_from_late_days(late_days) if leave_policy else 0

		if cint(self.set_lwp_manually):
			self.late_days = cint(late_days)
			self.leave_without_pay = flt(lwp)
			if not self.leave_without_pay:
				self.leave_without_pay = late_lwp
		else:
			self.late_days = cint(self.actual_late_days)
			self.leave_without_pay = self.actual_leave_without_pay

		if self.leave_without_pay != self.actual_leave_without_pay:
			frappe.msgprint(_("Leave Without Pay does not match with Attendance and approved Leave Application records"),
				indicator='orange', alert=1)

		payment_days = flt(self.get_payment_days(joining_date, relieving_date)) - flt(self.leave_without_pay)
		self.payment_days = payment_days > 0 and payment_days or 0

	def get_payment_days(self, joining_date, relieving_date):
		start_date = getdate(self.start_date)
		if joining_date:
			if getdate(self.start_date) <= joining_date <= getdate(self.end_date):
				start_date = joining_date
			elif joining_date > getdate(self.end_date):
				return

		end_date = getdate(self.end_date)
		if relieving_date:
			if getdate(self.start_date) <= relieving_date <= getdate(self.end_date):
				end_date = relieving_date
			elif relieving_date < getdate(self.start_date):
				frappe.throw(_("Employee relieved on {0} must be set as 'Left'")
					.format(relieving_date))

		payment_days = date_diff(end_date, start_date) + 1

		if not cint(frappe.get_cached_value("HR Settings", None, "include_holidays_in_total_working_days")):
			holidays = self.get_holidays_for_employee(start_date, end_date)
			payment_days -= len(holidays)
		return payment_days

	def get_holidays_for_employee(self, start_date, end_date):
		holiday_list = get_holiday_list_for_employee(self.employee)
		holidays = frappe.db.sql_list('''select holiday_date from `tabHoliday`
			where
				parent=%(holiday_list)s
				and holiday_date >= %(start_date)s
				and holiday_date <= %(end_date)s''', {
					"holiday_list": holiday_list,
					"start_date": start_date,
					"end_date": end_date
				})

		holidays = [cstr(i) for i in holidays]

		return holidays

	def get_leave_count(self, holidays, working_days, joining_date, relieving_date):
		holidays = "','".join(holidays)

		start_date = self.start_date
		if joining_date and getdate(self.start_date) <= getdate(joining_date) <= getdate(self.end_date):
			start_date = joining_date

		end_date = self.end_date
		if relieving_date and getdate(self.start_date) <= getdate(relieving_date) <= getdate(self.end_date):
			end_date = relieving_date

		out = frappe._dict({
			'leave_without_pay': 0,
			'leave_with_pay': 0,
			'late_leave_with_pay': 0,
			'total_leave': 0,
		})

		for d in range(working_days):
			dt = add_days(cstr(getdate(self.start_date)), d)
			leave = frappe.db.sql("""
				SELECT app.name, type.is_lwp,
					CASE
						WHEN app.half_day_date = %(dt)s or app.to_date = app.from_date
						THEN app.half_day else 0
					END as half_day
				FROM `tabLeave Application` app, `tabLeave Type` type
				WHERE type.name = app.leave_type
				AND app.docstatus = 1
				AND app.late_deduction = 0
				AND app.employee = %(employee)s
				AND CASE
					WHEN type.include_holiday != 1 THEN %(dt)s not in ('{0}') and %(dt)s between from_date and to_date and ifnull(app.salary_slip, '') = ''
					WHEN type.include_holiday THEN %(dt)s between from_date and to_date and ifnull(app.salary_slip, '') = ''
				END
			""".format(holidays), {"employee": self.employee, "dt": dt}, as_dict=1)

			if leave:
				leave = leave[0]
				leave_count = 0.5 if cint(leave.half_day) else 1

				out.total_leave += leave_count
				if leave.is_lwp:
					out.leave_without_pay += leave_count
				else:
					out.leave_with_pay += leave_count

		# Late Deduction Leaves
		late_leave_data = frappe.db.sql("""
			select type.is_lwp, -1 * sum(lle.leaves) as leaves
			from `tabLeave Ledger Entry` lle
			left join `tabLeave Type` type on type.name = lle.leave_type
			where lle.docstatus = 1 and lle.is_late_deduction = 1
				and lle.employee = %(employee)s
				and lle.from_date <= %(end_dt)s and %(st_dt)s <= lle.to_date
			group by lle.is_lwp
		""", {"employee": self.employee, "st_dt": start_date, "end_dt": end_date}, as_dict=1)

		for lle in late_leave_data:
			out.total_leave += lle.leaves
			if lle.is_lwp:
				out.leave_without_pay += lle.leaves
			else:
				out.late_leave_with_pay += lle.leaves
				out.leave_with_pay += lle.leaves

		if not cint(frappe.get_cached_value("HR Settings", None, "do_not_consider_absent_as_lwp")):
			absent = frappe.db.sql("""
				SELECT sum(CASE
					WHEN att.status = 'Half Day' THEN 0.5
					WHEN att.status = 'Absent' THEN 1
					ELSE 0 END)
				FROM `tabAttendance` as att
				WHERE att.docstatus = 1
				AND ifnull(leave_application, '') = ''
				AND employee = %(employee)s
				AND attendance_date between %(st_dt)s AND %(end_dt)s
			""", {"employee": self.employee, "st_dt": start_date, "end_dt": end_date})

			absent_days = flt(absent[0][0]) if absent else 0
			out.leave_without_pay += absent_days

		return out

	def add_earning_for_hourly_wages(self, doc, salary_component, amount):
		row_exists = False
		for row in doc.earnings:
			if row.salary_component == salary_component:
				row.amount = amount
				row_exists = True
				break

		if not row_exists:
			wages_row = {
				"salary_component": salary_component,
				"abbr": frappe.db.get_value("Salary Component", salary_component, "salary_component_abbr"),
				"amount": self.hour_rate * self.total_working_hours,
				"default_amount": 0.0,
				"additional_amount": 0.0
			}
			doc.append('earnings', wages_row)

	def remove_zero_components(self):
		to_remove = []
		for d in self.get("earnings"):
			if not flt(d.amount):
				to_remove.append(d)

		for d in self.get("deductions"):
			if not flt(d.amount):
				to_remove.append(d)

		for d in to_remove:
			self.remove(d)

	def calculate_net_pay(self):
		if self.salary_structure:
			self.calculate_component_amounts("earnings")
		self.gross_pay = self.get_component_totals("earnings")

		if self.salary_structure:
			self.calculate_component_amounts("deductions")
		self.total_deduction = self.get_component_totals("deductions")

		self.get_pending_advances()
		self.set_loan_repayment()

		self.net_pay = flt(self.gross_pay) - (flt(self.total_deduction) + flt(self.total_loan_repayment))

		if self.advances:
			for d in self.advances:
				d.allocated_amount = min(d.advance_amount, self.net_pay) if self.net_pay > 0 else 0
				d.balance_amount = flt(d.advance_amount) - flt(d.allocated_amount)
				self.net_pay -= d.allocated_amount

		self.total_advance_amount = sum([d.allocated_amount for d in self.advances])

		self.rounded_total = rounded(self.net_pay)

	def calculate_component_amounts(self, component_type):
		if not getattr(self, '_salary_structure_doc', None):
			self._salary_structure_doc = frappe.get_doc('Salary Structure', self.salary_structure)

		payroll_period = get_payroll_period(self.start_date, self.end_date, self.company)

		self.add_structure_components(component_type)
		self.add_additional_salary_components(component_type)
		if component_type == "earnings":
			self.add_employee_benefits(payroll_period)
		else:
			self.add_tax_components(payroll_period)

		self.set_component_amounts_based_on_payment_days(component_type)

	def add_structure_components(self, component_type):
		data = self.get_data_for_eval()
		for struct_row in self._salary_structure_doc.get(component_type):
			amount = self.eval_condition_and_formula(struct_row, data)
			if struct_row.statistical_component == 0:
				self.update_component_row(struct_row, amount, component_type)

	def get_data_for_eval(self):
		'''Returns data for evaluating formula'''
		data = frappe._dict()

		salary_structure_assignment = get_salary_structure_assignment(self.employee, self.salary_structure,
			self.end_date or self.posting_date)
		data.update(frappe.get_doc("Salary Structure Assignment", salary_structure_assignment).as_dict())

		data.update(frappe.get_doc("Employee", self.employee).as_dict())
		data.update(self.as_dict())

		# set values for components
		salary_components = frappe.get_all("Salary Component", fields=["salary_component_abbr"])
		for sc in salary_components:
			data.setdefault(sc.salary_component_abbr, 0)

		for key in ('earnings', 'deductions'):
			for d in self.get(key):
				data[d.abbr] = d.amount

		return data

	def eval_condition_and_formula(self, d, data):
		try:
			condition = d.condition.strip().replace("\n", " ") if d.condition else None
			if condition:
				if not frappe.safe_eval(condition, self.whitelisted_globals, data):
					return None
			amount = d.amount
			if d.amount_based_on_formula:
				formula = d.formula.strip().replace("\n", " ") if d.formula else None
				if formula:
					amount = flt(frappe.safe_eval(formula, self.whitelisted_globals, data), d.precision("amount"))
			if amount:
				data[d.abbr] = amount

			return amount

		except NameError as err:
			frappe.throw(_("Name error: {0}".format(err)))
		except SyntaxError as err:
			frappe.throw(_("Syntax error in formula or condition: {0}".format(err)))
		except Exception as e:
			frappe.throw(_("Error in formula or condition: {0}".format(e)))
			raise

	def add_employee_benefits(self, payroll_period):
		for struct_row in self._salary_structure_doc.get("earnings"):
			if struct_row.is_flexible_benefit == 1:
				if frappe.db.get_value("Salary Component", struct_row.salary_component, "pay_against_benefit_claim") != 1:
					benefit_component_amount = get_benefit_component_amount(self.employee, self.start_date, self.end_date,
						struct_row.salary_component, self._salary_structure_doc, self.payroll_frequency, payroll_period)
					if benefit_component_amount:
						self.update_component_row(struct_row, benefit_component_amount, "earnings")
				else:
					benefit_claim_amount = get_benefit_claim_amount(self.employee, self.start_date, self.end_date, struct_row.salary_component)
					self.update_component_row(struct_row, benefit_claim_amount, "earnings")

		self.adjust_benefits_in_last_payroll_period(payroll_period)

	def adjust_benefits_in_last_payroll_period(self, payroll_period):
		if payroll_period:
			if (getdate(payroll_period.end_date) <= getdate(self.end_date)):
				last_benefits = get_last_payroll_period_benefits(self.employee, self.start_date, self.end_date,
					payroll_period, self._salary_structure_doc)
				if last_benefits:
					for last_benefit in last_benefits:
						last_benefit = frappe._dict(last_benefit)
						amount = last_benefit.amount
						self.update_component_row(frappe._dict(last_benefit.struct_row), amount, "earnings")

	def add_additional_salary_components(self, component_type):
		additional_components = get_additional_salary_component(self.employee,
			self.start_date, self.end_date, component_type)
		self.additional_components = additional_components
		if additional_components:
			for additional_component in additional_components:
				amount = additional_component.amount
				overwrite = additional_component.overwrite
				self.update_component_row(frappe._dict(additional_component.struct_row), amount,
					component_type, overwrite=overwrite)

	def add_tax_components(self, payroll_period):
		# Calculate variable_based_on_taxable_salary after all components updated in salary slip
		tax_components, other_deduction_components = [], []
		for d in self._salary_structure_doc.get("deductions"):
			if d.variable_based_on_taxable_salary == 1 and not d.formula and not flt(d.amount):
				tax_components.append(d.salary_component)
			else:
				other_deduction_components.append(d.salary_component)

		if not tax_components:
			tax_components = [d.name for d in frappe.get_all("Salary Component", filters={"variable_based_on_taxable_salary": 1})
				if d.name not in other_deduction_components]

		overwritten_tax_components = [ac.struct_row.salary_component for ac in self.additional_components if ac.overwrite]
		for d in tax_components:
			if d not in overwritten_tax_components:
				tax_amount = self.calculate_variable_based_on_taxable_salary(d, payroll_period)
				tax_row = self.get_salary_slip_row(d)
				self.update_component_row(tax_row, tax_amount, "deductions")

	def update_component_row(self, struct_row, amount, key, overwrite=1):
		component_row = None
		for d in self.get(key):
			if d.salary_component == struct_row.salary_component:
				component_row = d

		if not component_row:
			if amount:
				self.append(key, {
					'amount': amount,
					'default_amount': amount if not struct_row.get("is_additional_component") else 0,
					'depends_on_payment_days' : struct_row.depends_on_payment_days,
					'salary_component' : struct_row.salary_component,
					'abbr' : struct_row.abbr,
					'do_not_include_in_total' : struct_row.do_not_include_in_total,
					'is_tax_applicable': struct_row.is_tax_applicable,
					'is_flexible_benefit': struct_row.is_flexible_benefit,
					'variable_based_on_taxable_salary': struct_row.variable_based_on_taxable_salary,
					'deduct_full_tax_on_selected_payroll_date': struct_row.deduct_full_tax_on_selected_payroll_date,
					'additional_amount': amount if struct_row.get("is_additional_component") else 0,
					'exempted_from_income_tax': struct_row.exempted_from_income_tax
				})
		else:
			if struct_row.get("is_additional_component"):
				if overwrite:
					component_row.additional_amount = amount - component_row.get("default_amount", 0)
				else:
					component_row.additional_amount = amount

				if not overwrite and component_row.default_amount:
					amount += component_row.default_amount
			else:
				component_row.default_amount = amount

			component_row.amount = amount
			component_row.deduct_full_tax_on_selected_payroll_date = struct_row.deduct_full_tax_on_selected_payroll_date

	def calculate_variable_based_on_taxable_salary(self, tax_component, payroll_period):
		if not payroll_period:
			frappe.msgprint(_("Start and end dates not in a valid Payroll Period, cannot calculate {0}.")
				.format(tax_component))
			return

		# Deduct taxes forcefully for unsubmitted tax exemption proof and unclaimed benefits in the last period
		if payroll_period.end_date <= getdate(self.end_date):
			self.deduct_tax_for_unsubmitted_tax_exemption_proof = 1
			self.deduct_tax_for_unclaimed_employee_benefits = 1

		return self.calculate_variable_tax(payroll_period, tax_component)

	def calculate_variable_tax(self, payroll_period, tax_component):
		# get Tax slab from salary structure assignment for the employee and payroll period
		tax_slab = self.get_income_tax_slabs(payroll_period)
		if not tax_slab:
			return 0

		# get remaining numbers of sub-period (period for which one salary is processed)
		remaining_sub_periods = get_period_factor(self.employee,
			self.start_date, self.end_date, self.payroll_frequency, payroll_period)[1]
		# get taxable_earnings, paid_taxes for previous period
		previous_taxable_earnings = self.get_taxable_earnings_for_prev_period(payroll_period.start_date,
			self.start_date, tax_slab.allow_tax_exemption)
		previous_total_paid_taxes = self.get_tax_paid_in_period(payroll_period.start_date, self.start_date, tax_component)

		opening_tax_details = self.get_opening_income_tax_details(payroll_period)
		previous_taxable_earnings += opening_tax_details.taxable_earnings
		previous_total_paid_taxes += opening_tax_details.deducted_amount

		# get taxable_earnings for current period (all days)
		current_taxable_earnings = self.get_taxable_earnings(tax_slab.allow_tax_exemption)
		future_structured_taxable_earnings = current_taxable_earnings.taxable_earnings * (math.ceil(remaining_sub_periods) - 1)

		# get taxable_earnings, addition_earnings for current actual payment days
		current_taxable_earnings_for_payment_days = self.get_taxable_earnings(tax_slab.allow_tax_exemption, based_on_payment_days=1)
		current_structured_taxable_earnings = current_taxable_earnings_for_payment_days.taxable_earnings
		current_additional_earnings = current_taxable_earnings_for_payment_days.additional_income
		current_additional_earnings_with_full_tax = current_taxable_earnings_for_payment_days.additional_income_with_full_tax

		# Get taxable unclaimed benefits
		unclaimed_taxable_benefits = 0
		if self.deduct_tax_for_unclaimed_employee_benefits:
			unclaimed_taxable_benefits = self.calculate_unclaimed_taxable_benefits(payroll_period)
			unclaimed_taxable_benefits += current_taxable_earnings_for_payment_days.flexi_benefits

		# Total exemption amount based on tax exemption declaration
		total_exemption_amount = self.get_total_exemption_amount(payroll_period, tax_slab)

		#Employee Other Incomes
		other_incomes = self.get_income_form_other_sources(payroll_period) or 0.0

		# Total taxable earnings including additional and other incomes
		total_taxable_earnings = previous_taxable_earnings + current_structured_taxable_earnings + future_structured_taxable_earnings \
			+ current_additional_earnings + other_incomes + unclaimed_taxable_benefits - total_exemption_amount
		
		# Total taxable earnings without additional earnings with full tax
		total_taxable_earnings_without_full_tax_addl_components = total_taxable_earnings - current_additional_earnings_with_full_tax

		# Structured tax amount
		total_structured_tax_amount = self.calculate_tax_by_tax_slab(
			total_taxable_earnings_without_full_tax_addl_components, tax_slab)
		current_structured_tax_amount = (total_structured_tax_amount - previous_total_paid_taxes) / remaining_sub_periods
		
		# Total taxable earnings with additional earnings with full tax
		full_tax_on_additional_earnings = 0.0
		if current_additional_earnings_with_full_tax:
			total_tax_amount = self.calculate_tax_by_tax_slab(total_taxable_earnings, tax_slab)
			full_tax_on_additional_earnings = total_tax_amount - total_structured_tax_amount

		current_tax_amount = current_structured_tax_amount + full_tax_on_additional_earnings
		if flt(current_tax_amount) < 0:
			current_tax_amount = 0

		return current_tax_amount

	def get_income_tax_slabs(self, payroll_period):
		income_tax_exempt = cint(frappe.db.get_value("Salary Structure Assignment",
			{"employee": self.employee, "salary_structure": self.salary_structure, "docstatus": 1}, ["income_tax_exempt"]))

		if income_tax_exempt:
			return None

		income_tax_slab = get_applicable_income_tax_slab(payroll_period.start_date, self.company)
		if not income_tax_slab:
			return None

		income_tax_slab_doc = frappe.get_cached_doc("Income Tax Slab", income_tax_slab)
		return income_tax_slab_doc

	def get_taxable_earnings_for_prev_period(self, start_date, end_date, allow_tax_exemption=False):
		taxable_earnings = frappe.db.sql("""
			select sum(sd.amount)
			from
				`tabSalary Detail` sd join `tabSalary Slip` ss on sd.parent=ss.name
			where 
				sd.parentfield='earnings'
				and sd.is_tax_applicable=1
				and is_flexible_benefit=0
				and ss.docstatus=1
				and ss.employee=%(employee)s
				and ss.start_date between %(from_date)s and %(to_date)s
				and ss.end_date between %(from_date)s and %(to_date)s
			""", {
				"employee": self.employee,
				"from_date": start_date,
				"to_date": end_date
			})
		taxable_earnings = flt(taxable_earnings[0][0]) if taxable_earnings else 0

		exempted_amount = 0
		if allow_tax_exemption:
			exempted_amount = frappe.db.sql("""
				select sum(sd.amount)
				from
					`tabSalary Detail` sd join `tabSalary Slip` ss on sd.parent=ss.name
				where
					sd.parentfield='deductions'
					and sd.exempted_from_income_tax=1
					and is_flexible_benefit=0
					and ss.docstatus=1
					and ss.employee=%(employee)s
					and ss.start_date between %(from_date)s and %(to_date)s
					and ss.end_date between %(from_date)s and %(to_date)s
				""", {
					"employee": self.employee,
					"from_date": start_date,
					"to_date": end_date
				})
			exempted_amount = flt(exempted_amount[0][0]) if exempted_amount else 0

		return taxable_earnings - exempted_amount

	def get_tax_paid_in_period(self, start_date, end_date, tax_component):
		# find total_tax_paid, tax paid for benefit, additional_salary
		total_tax_paid = flt(frappe.db.sql("""
			select
				sum(sd.amount)
			from
				`tabSalary Detail` sd join `tabSalary Slip` ss on sd.parent=ss.name
			where
				sd.parentfield='deductions'
				and sd.salary_component=%(salary_component)s
				and sd.variable_based_on_taxable_salary=1
				and ss.docstatus=1
				and ss.employee=%(employee)s
				and ss.start_date between %(from_date)s and %(to_date)s
				and ss.end_date between %(from_date)s and %(to_date)s
		""", {
			"salary_component": tax_component,
			"employee": self.employee,
			"from_date": start_date,
			"to_date": end_date
		})[0][0])

		return total_tax_paid

	def get_opening_income_tax_details(self, payroll_period):
		opening_tax_details = frappe.db.sql("""
			select
				ifnull(sum(deducted_amount), 0) as deducted_amount,
				ifnull(sum(taxable_earnings), 0) as taxable_earnings
			from `tabEmployee Opening Income Tax`
			where payroll_period = %s and employee = %s and docstatus = 1
		""", [payroll_period.name, self.employee], as_dict=1)
		return opening_tax_details[0]

	def get_taxable_earnings(self, allow_tax_exemption=False, based_on_payment_days=0):
		joining_date, relieving_date = frappe.get_cached_value("Employee", self.employee,
			["date_of_joining", "relieving_date"])

		if not relieving_date:
			relieving_date = getdate(self.end_date)

		if not joining_date:
			frappe.throw(_("Please set the Date of Joining for employee {0}").format(frappe.bold(self.employee_name)))

		taxable_earnings = 0
		additional_income = 0
		additional_income_with_full_tax = 0
		flexi_benefits = 0

		for earning in self.earnings:
			if based_on_payment_days:
				amount, additional_amount = self.get_amount_based_on_payment_days(earning, joining_date, relieving_date)
			else:
				amount, additional_amount = earning.amount, earning.additional_amount

			if earning.is_tax_applicable:
				if additional_amount:
					taxable_earnings += (amount - additional_amount)
					additional_income += additional_amount
					if earning.deduct_full_tax_on_selected_payroll_date:
						additional_income_with_full_tax += additional_amount
					continue

				if earning.is_flexible_benefit:
					flexi_benefits += amount
				else:
					taxable_earnings += amount

		if allow_tax_exemption:
			for ded in self.deductions:
				if ded.exempted_from_income_tax:
					amount = ded.amount
					if based_on_payment_days:
						amount = self.get_amount_based_on_payment_days(ded, joining_date, relieving_date)[0]
					taxable_earnings -= flt(amount)

		return frappe._dict({
			"taxable_earnings": taxable_earnings,
			"additional_income": additional_income,
			"additional_income_with_full_tax": additional_income_with_full_tax,
			"flexi_benefits": flexi_benefits
		})

	def get_amount_based_on_payment_days(self, row, joining_date, relieving_date):
		payment_days = flt(self.payment_days)
		if frappe.get_cached_value("HR Settings", None, "consider_lwp_as_deduction"):
			payment_days += flt(self.leave_without_pay)

		amount, additional_amount = row.amount, row.additional_amount
		if (self.salary_structure and
			cint(row.depends_on_payment_days) and cint(self.total_working_days) and
			(not self.salary_slip_based_on_timesheet or
				getdate(self.start_date) < joining_date or
				getdate(self.end_date) > relieving_date
			)):
			additional_amount = flt((flt(row.additional_amount) * flt(payment_days)
				/ cint(self.total_working_days)), row.precision("additional_amount"))
			amount = flt((flt(row.default_amount) * flt(payment_days)
				/ cint(self.total_working_days)), row.precision("amount")) + additional_amount

		elif not payment_days and not self.salary_slip_based_on_timesheet and cint(row.depends_on_payment_days):
			amount, additional_amount = 0, 0
		elif not row.amount:
			amount = flt(row.default_amount) + flt(row.additional_amount)

		# apply rounding
		if frappe.get_cached_value("Salary Component", row.salary_component, "round_to_the_nearest_integer"):
			amount, additional_amount = rounded(amount), rounded(additional_amount)

		return amount, additional_amount

	def calculate_unclaimed_taxable_benefits(self, payroll_period):
		# get total sum of benefits paid
		total_benefits_paid = flt(frappe.db.sql("""
			select sum(sd.amount)
			from `tabSalary Detail` sd join `tabSalary Slip` ss on sd.parent=ss.name
			where
				sd.parentfield='earnings'
				and sd.is_tax_applicable=1
				and is_flexible_benefit=1
				and ss.docstatus=1
				and ss.employee=%(employee)s
				and ss.start_date between %(start_date)s and %(end_date)s
				and ss.end_date between %(start_date)s and %(end_date)s
		""", {
			"employee": self.employee,
			"start_date": payroll_period.start_date,
			"end_date": self.start_date
		})[0][0])

		# get total benefits claimed
		total_benefits_claimed = flt(frappe.db.sql("""
			select sum(claimed_amount)
			from `tabEmployee Benefit Claim`
			where
				docstatus=1
				and employee=%s
				and claim_date between %s and %s
		""", (self.employee, payroll_period.start_date, self.end_date))[0][0])

		return total_benefits_paid - total_benefits_claimed

	def get_total_exemption_amount(self, payroll_period, tax_slab):
		total_exemption_amount = 0
		if tax_slab.allow_tax_exemption:
			if self.deduct_tax_for_unsubmitted_tax_exemption_proof:
				exemption_proof = frappe.db.get_value("Employee Tax Exemption Proof Submission",
					{"employee": self.employee, "payroll_period": payroll_period.name, "docstatus": 1},
					["exemption_amount"])
				if exemption_proof:
					total_exemption_amount = exemption_proof
			else:
				declaration = frappe.db.get_value("Employee Tax Exemption Declaration",
					{"employee": self.employee, "payroll_period": payroll_period.name, "docstatus": 1},
					["total_exemption_amount"])
				if declaration:
					total_exemption_amount = declaration

			total_exemption_amount += flt(tax_slab.standard_tax_exemption_amount)

		return total_exemption_amount

	def get_income_form_other_sources(self, payroll_period):
		return frappe.get_all("Employee Other Income",
			filters={
				"employee": self.employee,
				"payroll_period": payroll_period.name,
				"company": self.company,
				"docstatus": 1
			},
			fields="SUM(amount) as total_amount"
		)[0].total_amount

	def calculate_tax_by_tax_slab(self, annual_taxable_earning, tax_slab):
		data = self.get_data_for_eval()
		data.update({"annual_taxable_earning": annual_taxable_earning})
		tax_amount = 0
		for slab in tax_slab.slabs:
			if slab.condition and not self.eval_tax_slab_condition(slab.condition, data):
				continue
			if not slab.to_amount and annual_taxable_earning >= slab.from_amount:
				tax_amount += (annual_taxable_earning - slab.from_amount) * slab.percent_deduction *.01
				continue
			if annual_taxable_earning >= slab.from_amount and annual_taxable_earning < slab.to_amount:
				tax_amount += (annual_taxable_earning - slab.from_amount) * slab.percent_deduction *.01
			elif annual_taxable_earning >= slab.from_amount and annual_taxable_earning >= slab.to_amount:
				tax_amount += (slab.to_amount - slab.from_amount) * slab.percent_deduction * .01

		# other taxes and charges on income tax
		for d in tax_slab.other_taxes_and_charges:
			if flt(d.min_taxable_income) and flt(d.min_taxable_income) > annual_taxable_earning:
				continue

			if flt(d.max_taxable_income) and flt(d.max_taxable_income) < annual_taxable_earning:
				continue
			
			tax_amount += tax_amount * flt(d.percent) / 100

		return tax_amount

	def eval_tax_slab_condition(self, condition, data):
		try:
			condition = condition.strip()
			if condition:
				return frappe.safe_eval(condition, self.whitelisted_globals, data)
		except NameError as err:
			frappe.throw(_("Name error: {0}".format(err)))
		except SyntaxError as err:
			frappe.throw(_("Syntax error in condition: {0}".format(err)))
		except Exception as e:
			frappe.throw(_("Error in formula or condition: {0}".format(e)))
			raise

	def get_salary_slip_row(self, salary_component):
		component = frappe.get_doc("Salary Component", salary_component)
		# Data for update_component_row
		struct_row = frappe._dict()
		struct_row['depends_on_payment_days'] = component.depends_on_payment_days
		struct_row['salary_component'] = component.name
		struct_row['abbr'] = component.salary_component_abbr
		struct_row['do_not_include_in_total'] = component.do_not_include_in_total
		struct_row['is_tax_applicable'] = component.is_tax_applicable
		struct_row['is_flexible_benefit'] = component.is_flexible_benefit
		struct_row['variable_based_on_taxable_salary'] = component.variable_based_on_taxable_salary
		return struct_row

	def get_component_totals(self, component_type):
		total = 0.0
		for d in self.get(component_type):
			if not d.do_not_include_in_total:
				d.amount = flt(d.amount, d.precision("amount"))
				total += d.amount
		return total

	def set_component_amounts_based_on_payment_days(self, component_type):
		joining_date, relieving_date = frappe.get_cached_value("Employee", self.employee,
			["date_of_joining", "relieving_date"])

		if not relieving_date:
			relieving_date = getdate(self.end_date)

		if not joining_date:
			frappe.throw(_("Please set the Date of Joining for employee {0}").format(frappe.bold(self.employee_name)))

		for d in self.get(component_type):
			d.amount = self.get_amount_based_on_payment_days(d, joining_date, relieving_date)[0]

	def set_loan_repayment(self):
		self.set('loans', [])
		self.total_loan_repayment = 0
		self.total_interest_amount = 0
		self.total_principal_amount = 0

		for loan in self.get_loan_details():
			self.append('loans', {
				'loan': loan.name,
				'repayment_amount': loan.total_payment,
				'interest_amount': loan.interest_amount,
				'principal_amount': loan.principal_amount,
				'loan_account': loan.loan_account,
				'interest_income_account': loan.interest_income_account,
				'loan_repayment_detail': loan.loan_repayment_detail,
				'loan_repayment_date': loan.payment_date,
				'loan_type': loan.loan_type,
				'disbursement_date': loan.disbursement_date,
				'total_loan_amount': loan.total_loan_amount,
				'pending_loan_amount': flt(loan.total_loan_amount) - flt(loan.total_amount_paid),
				'balance_amount': flt(loan.total_loan_amount) - flt(loan.total_amount_paid) - flt(loan.total_payment),
			})

			self.total_loan_repayment += loan.total_payment
			self.total_interest_amount += loan.interest_amount
			self.total_principal_amount += loan.principal_amount

	def get_loan_details(self):
		loan_filters = {
			'employee': self.employee,
			'start_date': self.start_date,
			'end_date': self.end_date
		}

		if frappe.db.get_single_value("HR Settings", "show_upcoming_loans_in_salary_slips"):
			return frappe.db.sql("""
				WITH loan_repayment_details AS (
					SELECT loan.name, loan.total_payment as total_loan_amount, loan.creation,
						loan.loan_type, loan.disbursement_date, loan.total_amount_paid,
						rps.name as loan_repayment_detail, rps.principal_amount, rps.interest_amount,
						rps.total_payment, rps.payment_date, loan.loan_account, loan.interest_income_account,
						RANK() OVER (PARTITION BY loan.name ORDER BY rps.payment_date ASC) AS r
					FROM
						`tabRepayment Schedule` as rps, `tabLoan` as loan
					WHERE
						loan.name = rps.parent
						and loan.docstatus = 1
						and rps.payment_date >= %(start_date)s
						and rps.paid = 0
						and loan.repay_from_salary = 1
						and loan.applicant_type = 'Employee'
						and loan.applicant = %(employee)s
					)
				SELECT name, total_loan_amount, loan_type, disbursement_date, total_amount_paid,
					loan_repayment_detail, principal_amount, interest_amount, payment_date, total_payment,
					CASE WHEN payment_date between %(start_date)s and %(end_date)s THEN total_payment ELSE 0 END AS total_payment
				FROM loan_repayment_details lrd
				WHERE r = 1
				order by payment_date, creation
			""", loan_filters, as_dict=1)

		return frappe.db.sql("""
			select loan.name, rps.name as loan_repayment_detail,
				rps.principal_amount, rps.interest_amount, rps.total_payment,
				rps.payment_date, loan.loan_account, loan.interest_income_account,
				loan.loan_type, loan.disbursement_date, loan.total_payment as total_loan_amount, loan.total_amount_paid
			from
				`tabRepayment Schedule` as rps, `tabLoan` as loan
			where
				loan.name = rps.parent
				and loan.docstatus = 1
				and rps.payment_date between %(start_date)s and %(end_date)s
				and rps.paid = 0
				and loan.repay_from_salary = 1
				and loan.applicant_type = 'Employee' and loan.applicant = %(employee)s
		""", loan_filters, as_dict=True)

	def update_salary_slip_in_additional_salary(self):
		salary_slip = self.name if self.docstatus==1 else None
		frappe.db.sql("""
			update `tabAdditional Salary` set salary_slip=%s
			where employee=%s and payroll_date between %s and %s and docstatus=1
		""", (salary_slip, self.employee, self.start_date, self.end_date))

	def email_salary_slip(self):
		receiver = frappe.db.get_value("Employee", self.employee, "prefered_email")
		hr_settings = frappe.get_cached_doc("HR Settings")
		message = "Please see attachment"
		password = None
		if hr_settings.encrypt_salary_slips_in_emails:
			password = generate_password_for_pdf(hr_settings.password_policy, self.employee)
			message += """<br>Note: Your salary slip is password protected,
				the password to unlock the PDF is of the format {0}. """.format(hr_settings.password_policy)

		if receiver:
			email_args = {
				"recipients": [receiver],
				"message": _(message),
				"subject": 'Salary Slip - from {0} to {1}'.format(self.start_date, self.end_date),
				"attachments": [frappe.attach_print(self.doctype, self.name, file_name=self.name, password=password)],
				"reference_doctype": self.doctype,
				"reference_name": self.name
				}
			if not frappe.flags.in_test:
				enqueue(method=frappe.sendmail, queue='short', timeout=300, is_async=True, **email_args)
			else:
				frappe.sendmail(**email_args)
		else:
			msgprint(_("{0}: Employee email not found, hence email not sent").format(self.employee_name))

	def update_status(self, salary_slip=None):
		for data in self.timesheets:
			if data.time_sheet:
				timesheet = frappe.get_doc('Timesheet', data.time_sheet)
				timesheet.salary_slip = salary_slip
				timesheet.flags.ignore_validate_update_after_submit = True
				timesheet.set_status()
				timesheet.save()

	def update_loans(self):
		loans = set()
		is_paid = 1 if self.docstatus == 1 else 0

		for loan in self.loans:
			if loan.loan_repayment_detail and loan.repayment_amount > 0:
				loans.add(loan.loan)
				frappe.db.set_value("Repayment Schedule", loan.loan_repayment_detail, "paid", is_paid)

		for loan in loans:
			doc = frappe.get_doc("Loan", loan)
			doc.update_total_amount_paid()
			doc.set_status(update=True)

	def set_status(self, status=None):
		'''Get and update status'''
		if not status:
			status = self.get_status()
		self.db_set("status", status)

	def process_salary_structure(self, for_preview=0):
		'''Calculate salary after salary structure details have been updated'''
		if not self.salary_slip_based_on_timesheet:
			self.get_date_details()
		self.set_employee_details()
		self.get_leave_details(for_preview=for_preview)
		self.calculate_net_pay()

	def set_employee_details(self):
		employee_details = frappe.db.get_value("Employee", self.employee, [
			"department", "designation", "branch",
			"salary_mode", "bank_name", "bank_ac_no",
			"date_of_joining", "relieving_date",
		], as_dict=1)

		if employee_details:
			self.department = employee_details.department
			self.designation = employee_details.designation
			self.branch = employee_details.branch

			self.salary_mode = employee_details.salary_mode
			self.bank_name = employee_details.bank_name if self.salary_mode == "Bank" else None
			self.bank_account_no = employee_details.bank_ac_no if self.salary_mode == "Bank" else None

			self.joining_date = employee_details.date_of_joining

			if employee_details.relieving_date and self.start_date and self.end_date\
					and getdate(self.start_date) <= getdate(employee_details.relieving_date) <= getdate(self.end_date):
				self.relieving_date = employee_details.relieving_date
			else:
				self.relieving_date = None

			department_cost_center = get_department_cost_center(self.department)
			if department_cost_center:
				self.cost_center = department_cost_center

	@frappe.whitelist()
	def process_salary_based_on_leave(self, lwp=0, late_days=0):
		self.get_leave_details(lwp=lwp, late_days=late_days)
		self.calculate_net_pay()

	def get_pending_advances(self):
		self.advances = []

		pending_advances = frappe.db.sql("""
			select name as employee_advance, posting_date, advance_account, balance_amount as advance_amount
			from `tabEmployee Advance`
			where docstatus=1 and employee=%s and posting_date <= %s and deduct_from_salary = 1 and balance_amount > 0
			order by posting_date
		""", [self.employee, self.end_date], as_dict=1)

		for data in pending_advances:
			self.append('advances', data)

	@frappe.whitelist()
	def calculate_mode_of_payment(self):
		total = self.net_pay if self.is_rounding_total_disabled() else self.rounded_total

		standard_mode_field = scrub(cstr(self.salary_mode)) + "_amount"
		if not self.salary_mode or not self.meta.has_field(standard_mode_field):
			self.reset_mode_of_payment_amount()
			self.no_mode_amount = total
			return

		# reset amounts if salary mode changed and running from payroll entry
		if not self.is_new() and self.flags.from_payroll_entry and cstr(self.salary_mode) != cstr(self.db_get('salary_mode')):
			self.reset_mode_of_payment_amount()

		# round values according to net pay precision
		fieldnames = ['bank_amount', 'cheque_amount', 'cash_amount', 'no_mode_amount']
		for f in fieldnames:
			self.set(f, flt(self.get(f)), self.precision('net_pay'))

		# calculate non standard amount
		non_standard_amount = 0
		for f in fieldnames:
			if f != standard_mode_field:
				non_standard_amount += flt(self.get(f))

		non_standard_amount = flt(non_standard_amount, self.precision('net_pay'))
		standard_amount = flt(total - non_standard_amount, self.precision('net_pay'))
		self.set(standard_mode_field, standard_amount)

	def validate_mode_of_payment(self):
		fieldnames = ['bank_amount', 'cheque_amount', 'cash_amount', 'no_mode_amount']
		for f in fieldnames:
			self.validate_value(f, ">=", 0.0)

	def reset_mode_of_payment_amount(self):
		fieldnames = ['bank_amount', 'cheque_amount', 'cash_amount', 'no_mode_amount']
		for f in fieldnames:
			self.set(f, 0)


def unlink_ref_doc_from_salary_slip(ref_no):
	linked_salary_slips = frappe.db.sql_list("""
		select name
		from `tabSalary Slip`
		where journal_entry = %s and docstatus < 2
	""", ref_no)

	if linked_salary_slips:
		for salary_slip in linked_salary_slips:
			frappe.db.set_value("Salary Slip", salary_slip, "journal_entry", None, notify=1)


def generate_password_for_pdf(policy_template, employee):
	employee = frappe.get_doc("Employee", employee)
	return policy_template.format(**employee.as_dict())
