import "./conf.js"
import "./utils.js"
import "./queries.js"
import "./help_links.js"
import "./utils/dimension_tree_filter.js"
import "./templates/lcv_manual_distribution.html"

// Controllers
import "./utils/party.js"
import "./controllers/stock_controller.js"
import "./controllers/packing_controller.js"
import "./payment/payments.js"
import "./controllers/taxes_and_totals.js"
import "./controllers/transaction.js"
import "./controllers/applies_to_common.js"
import "./utils/manufacturing.js"

// Item Selector
import "./templates/item_selector.html"
import "./utils/item_selector.js"
import "./utils/serial_batch_selector.js"
import "./utils/barcode_scanner.js"

// Quick Entries
import "./utils/item_quick_entry.js"
import "./templates/item_quick_entry.html"
import "./utils/customer_quick_entry.js"
import "./utils/insurance_surveyor_quick_entry.js"
import "./utils/vehicle_quick_entry.js"

// HR
import "./templates/employees_to_mark_attendance.html"

// POS
import "./pos/pos.html"
import "./pos/pos_bill_item.html"
import "./pos/pos_bill_item_new.html"
import "./pos/pos_selected_item.html"
import "./pos/pos_item.html"
import "./pos/pos_tax_row.html"
import "./pos/pos_invoice_list.html"
import "./pos/customer_toolbar.html"
import "./payment/pos_payment.html"
import "./payment/payment_details.html"

// Dynamic Bundling
import "./utils/bundling.js"

// Vehicles Domain
import "./controllers/vehicle_pricing.js"
import "./controllers/vehicle_booking.js"
import "./controllers/vehicle_transaction.js"
import "./controllers/vehicle_additional_service.js"
import "../../vehicles/page/workshop_cp/templates/workshop_cp_layout.html"
import "../../vehicles/page/workshop_cp/templates/workshop_cp_vehicles.html"
import "../../vehicles/page/workshop_cp/templates/workshop_cp_vehicle_row.html"
import "../../vehicles/page/workshop_cp/templates/workshop_cp_tasks.html"
import "../../vehicles/page/workshop_cp/templates/workshop_cp_task_row.html"


// Agriculture Domain
import "./agriculture/ternary_plot.js"

// Education Domain
import "./education/student_button.html"
import "./education/assessment_result_tool.html"

// Maintenance Schedule
import "./templates/maintenance_schedule.html"
