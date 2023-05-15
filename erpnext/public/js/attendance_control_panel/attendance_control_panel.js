import Vue from "vue/dist/vue.js";
import AttendanceControlPanel from "./AttendanceControlPanel.vue";

import BootstrapVue from 'bootstrap-vue'

Vue.prototype.__ = window.__;
Vue.prototype.frappe = window.frappe;
Vue.use(BootstrapVue)

frappe.provide('erpnext.hr');

erpnext.hr.attendance_control_panel = new Vue({
    el: ".attendance-control-panel",
    render: h => h(AttendanceControlPanel)
});
