import Vue from "vue/dist/vue.js";
import AttendanceControlPanel from "./AttendanceControlPanel.vue";

Vue.prototype.__ = window.__;
Vue.prototype.frappe = window.frappe;

frappe.provide('erpnext.hr');

erpnext.hr.attendance_control_panel = new Vue({
    el: ".attendance-control-panel",
    render: h => h(AttendanceControlPanel)
});
