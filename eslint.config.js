const js = require("@eslint/js");
const stylistic = require("@stylistic/eslint-plugin");
const globals = require("globals");

// Same globals as frappe's .eslintrc, plus the crm and erpnext namespaces
const frappe_globals = [
	"frappe", "Vue", "SetVueGlobals", "__", "repl", "Class", "locals", "cint", "cstr", "cur_frm", "cur_dialog",
	"cur_page", "cur_list", "cur_tree", "msg_dialog", "is_null", "in_list", "has_common", "posthog", "has_words",
	"validate_email", "open_web_template_values_editor", "validate_name", "validate_phone", "validate_url",
	"get_number_format", "format_number", "format_currency", "comment_when", "open_url_post", "toTitle", "lstrip",
	"rstrip", "strip", "strip_html", "replace_all", "flt", "precision", "CREATE", "AMEND", "CANCEL", "copy_dict",
	"get_number_format_info", "strip_number_groups", "print_table", "Layout", "web_form_settings", "$c", "$a", "$i",
	"$bg", "$y", "$c_obj", "refresh_many", "refresh_field", "toggle_field", "get_field_obj", "get_query_params",
	"unhide_field", "hide_field", "set_field_options", "getCookie", "getCookies", "get_url_arg", "md5", "$", "jQuery",
	"moment", "hljs", "Awesomplete", "Sortable", "Showdown", "Taggle", "Gantt", "Slick", "Webcam", "PhotoSwipe",
	"PhotoSwipeUI_Default", "io", "JsBarcode", "L", "Chart", "DataTable", "qz", "localforage", "extend_cscript",
	"crm", "erpnext",
];

// Form scripts may start with a jinja `{% include "..." %}` line, which frappe expands when it serves the file.
// Lint them by turning each tag into a comment of the same length (`{%` -> `/*`, `%}` -> `*/`): every offset stays the
// same, so fixes apply to the real file, and ESLint leaves comments alone.
const jinja_tag = /^([ \t]*)\{%(.*)%\}/gm;
const jinja_include_processor = {
	meta: {name: "jinja-include"},
	supportsAutofix: true,
	preprocess(text) {
		return [text.replace(jinja_tag, "$1/*$2*/")];
	},
	postprocess(messages) {
		return messages[0];
	},
};

module.exports = [
	{
		ignores: ["erpnext/public/dist/**", "**/node_modules/**"],
	},
	js.configs.recommended,
	{
		files: ["**/*.js"],
		processor: jinja_include_processor,
		languageOptions: {
			ecmaVersion: 2022,
			sourceType: "module",
			globals: {
				...globals.browser,
				...globals.node,
				...Object.fromEntries(frappe_globals.map((name) => [name, "readonly"])),
			},
		},
		plugins: {
			"@stylistic": stylistic,
		},
		rules: {
			// frappe's rules
			"no-useless-escape": "off",
			"camelcase": "off",
			"no-unused-vars": "off",
			"no-console": "warn",
			"no-extra-boolean-cast": "off",
			"no-control-regex": "off",

			// Style: fixed automatically, line breaks are left as written
			"@stylistic/quotes": ["error", "double", {avoidEscape: true}],
			"@stylistic/semi": ["error", "always"],
			"@stylistic/comma-dangle": ["error", "always-multiline"],
			"@stylistic/operator-linebreak": ["error", "before"],
			"@stylistic/space-before-function-paren": ["error", {anonymous: "never", named: "never", asyncArrow: "always"}],
			"@stylistic/object-curly-spacing": ["error", "never"],
			"@stylistic/indent": ["error", "tab", {SwitchCase: 1}],
			"@stylistic/space-unary-ops": ["error", {words: true}],
			"@stylistic/keyword-spacing": "error",
			"@stylistic/space-infix-ops": "error",
			"@stylistic/comma-spacing": "error",
			"@stylistic/key-spacing": "error",
			"@stylistic/arrow-spacing": "error",
			"@stylistic/space-before-blocks": "error",
			"@stylistic/no-trailing-spaces": "error",
			"@stylistic/eol-last": "error",
			"@stylistic/no-multiple-empty-lines": ["error", {max: 2, maxEOF: 0}],
		},
	},
];
