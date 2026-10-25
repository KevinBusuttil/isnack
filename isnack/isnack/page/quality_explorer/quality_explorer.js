frappe.provide("isnack");

frappe.pages["quality-explorer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Quality Explorer"),
		single_column: true,
	});
	wrapper.quality_explorer = new isnack.QualityExplorer(page);
};

frappe.pages["quality-explorer"].on_page_show = function (wrapper) {
	// The URL names the subject on screen:
	//   /app/quality-explorer/Batch/<batch-id>
	//   /app/quality-explorer/Work Order/<work-order>
	// and the bare /app/quality-explorer (Back past the first pick) names none.
	const explorer = wrapper.quality_explorer;
	if (!explorer) return;
	const route = frappe.get_route() || [];
	if (route.length > 2) explorer.load_from_route(route[1], route.slice(2).join("/"));
	else explorer.clear();
};

const QE_METHOD = "isnack.isnack.page.quality_explorer.quality_explorer";
// the Batch Explorer's picker query: every word typed must match the batch, item code or item name
const QE_BATCH_QUERY = "isnack.isnack.page.batch_explorer.batch_explorer.search_batches";

isnack.QualityExplorer = class QualityExplorer {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.current_key = null;
		this.filter_text = "";
		this.loading = false;
		// bumped by every load, so only the latest response lands
		this.seq = 0;
		// per picker, the values it is being set to so it follows the URL
		this.syncing = { Batch: [], "Work Order": [] };
		// per picker, a change it was still validating when the page moved on
		this.stale_change = { Batch: false, "Work Order": false };
		// the route the explorer set itself last (a pick, adopt_name), as Kind/name
		this.own_route = null;
		this.reload_key = null;
		this.make();
	}

	make() {
		this.controls();
		this.layout();
		this.show_empty(__("Select a batch or a work order to see its quality records."));
	}

	controls() {
		this.batch_field = this.page.add_field({
			fieldname: "batch",
			label: __("Batch"),
			fieldtype: "Link",
			options: "Batch",
			get_query: () => ({ query: QE_BATCH_QUERY }),
			change: () => this.on_pick("Batch"),
		});
		this.batch_field.$input.attr("placeholder", __("Batch, item code or item name"));
		this.match_every_word();

		this.work_order_field = this.page.add_field({
			fieldname: "work_order",
			label: __("Work Order"),
			fieldtype: "Link",
			options: "Work Order",
			get_query: () => ({ filters: { docstatus: ["<", 2] } }),
			change: () => this.on_pick("Work Order"),
		});

		this.page.set_primary_action(
			__("Explore"),
			() => {
				const batch = this.batch_field.get_value();
				const work_order = this.work_order_field.get_value();
				if (batch) this.open("Batch", batch, true);
				else if (work_order) this.open("Work Order", work_order, true);
				else frappe.show_alert({ message: __("Please pick a batch or a work order"), indicator: "orange" });
			},
			"search"
		);

		this.expand_btn = this.page.add_button(__("Expand all"), () => this.toggle_all(true));
		this.collapse_btn = this.page.add_button(__("Collapse all"), () => this.toggle_all(false));
		this.pdf_btn = this.page.add_button(__("Save as PDF"), () => this.save_pdf());
		this.set_tree_buttons(false);
	}

	/** Enter/Tab only pick an option the typed text is part of (Frappe releases
	 *  that have ``input_matches_item``). search_batches matches each word on its
	 *  own, so "FG10005 crisps" lists batches whose text never holds that phrase:
	 *  accept an option holding every word too. As on the Batch Explorer. */
	match_every_word() {
		const field = this.batch_field;
		if (typeof field.input_matches_item !== "function") return;
		const frappe_match = field.input_matches_item.bind(field);
		field.input_matches_item = (input, item) => {
			if (frappe_match(input, item)) return true;
			if (!item.value || String(item.value).includes("__link_option")) return false;
			const text = `${item.value} ${item.description || ""}`.toLowerCase();
			return input.split(/\s+/).filter(Boolean).every((w) => text.includes(w));
		};
	}

	/** A pick by the user. One subject at a time: the other picker is emptied
	 *  (as the URL now names this one). A picker set to follow the URL is not a
	 *  pick: a Link validates on the server and reports the value it was set to
	 *  (in its stored spelling) when that returns, maybe after the user moved
	 *  on. A different value in that picker, or one in the other picker, is.
	 *  Nor is a change that began before the page last moved on: a Link checks
	 *  its value again on blur, so a click on a trace leaf or a link starts
	 *  one, which lands after that click has opened another subject or page. */
	on_pick(kind) {
		const field = kind === "Batch" ? this.batch_field : this.work_order_field;
		if (this.stale_change[kind]) {
			this.stale_change[kind] = false;
			this.sync_pickers();
			return;
		}
		// the user left the explorer: the address bar says so at once, the
		// router's route only once the next page has loaded (a Form fetches
		// its DocType first)
		if (frappe.router.get_sub_path().split("/")[0] !== "quality-explorer") return;
		const value = field.get_value();
		if (!value) return;
		if (this.syncing[kind].some((synced) => this.same_name(synced, value))) return;
		this.open(kind, value);
	}

	/** Explore by way of the URL, so the address bar, Back and a refresh always
	 *  name the subject on screen: on_page_show explores it. When the URL names
	 *  it already, in any spelling, no route change comes, so explore here,
	 *  unless it is on screen (a picker's second change on blur, which carries
	 *  the stored spelling). ``reload`` explores it again anyway (the Explore
	 *  button). */
	open(kind, name, reload = false) {
		const in_url = this.subject_in_url(kind, name);
		if (in_url !== null) {
			if (reload || !this.is_current(kind, in_url)) this.explore(kind, in_url);
			return;
		}
		if (reload) this.reload_key = `${kind}/${name}`;
		this.own_route = `${kind}/${name}`;
		frappe.set_route("quality-explorer", kind, name);
	}

	/** The name as the URL spells it when the URL names this subject, else null. */
	subject_in_url(kind, name) {
		const route = frappe.get_route() || [];
		if (route[0] !== "quality-explorer" || route[1] !== kind || route.length < 3) return null;
		const in_url = route.slice(2).join("/");
		return this.same_name(in_url, name) ? in_url : null;
	}

	/** The subject is on screen or on its way, in any spelling; after an error
	 *  it is neither. */
	is_current(kind, name) {
		const [current_kind, current_name] = this.split_key(this.current_key);
		return current_kind === kind && this.same_name(current_name, name) && (this.loading || !!this.data);
	}

	/** ``[kind, name]`` of a ``Kind/name`` key; a name may hold a slash itself. */
	split_key(key) {
		const cut = (key || "").indexOf("/");
		return cut > 0 ? [key.slice(0, cut), key.slice(cut + 1)] : [null, ""];
	}

	set_tree_buttons(enabled) {
		[this.expand_btn, this.collapse_btn, this.pdf_btn].forEach((b) => b && b.prop("disabled", !enabled));
	}

	layout() {
		this.body = $('<div class="qe-container"></div>').appendTo(this.page.main);
		this.$summary = $('<div class="qe-summary"></div>').appendTo(this.body);
		this.$coverage = $('<div class="qe-coverage"></div>').appendTo(this.body);
		this.$toolbar = $('<div class="qe-toolbar"></div>').appendTo(this.body);
		this.$tree = $('<div class="qe-tree"></div>').appendTo(this.body);
	}

	load_from_route(kind, name) {
		if (!["Batch", "Work Order"].includes(kind) || !name) return;
		// the user moving on (Back, a trace leaf, a link) supersedes a pick still
		// being checked; the explorer's own route (another pick landing,
		// adopt_name) does not
		const [own_kind, own_name] = this.split_key(this.own_route);
		this.own_route = null;
		if (own_kind !== kind || !this.same_name(own_name, name)) this.mark_stale_changes();
		const reload = this.reload_key === `${kind}/${name}`;
		this.reload_key = null;
		if (reload || !this.is_current(kind, name)) this.explore(kind, name);
		// on screen already under another spelling: the URL takes the stored one
		else if (this.data) this.adopt_name(kind, name, this.data.subject.name);
		this.sync_pickers();
	}

	/** Back to the bare page: no subject in the URL, so none on screen. */
	clear() {
		this.own_route = null;
		this.mark_stale_changes();
		this.seq += 1;
		this.current_key = null;
		this.loading = false;
		this.reload_key = null;
		this.show_empty(__("Select a batch or a work order to see its quality records."));
		this.sync_pickers();
	}

	/** The page moves on: a picker change still being validated is not a pick
	 *  (see on_pick). It swallows the picker's sync meanwhile, so when it lands
	 *  the picker follows the URL again. */
	mark_stale_changes() {
		if (this.batch_field.inside_change_event) this.stale_change.Batch = true;
		if (this.work_order_field.inside_change_event) this.stale_change["Work Order"] = true;
	}

	/** Set the pickers to the subject in the URL without that counting as a
	 *  pick. A set_value can be swallowed while an earlier one is still being
	 *  validated, so when the subject moved on meanwhile, follow it again. */
	sync_pickers() {
		const key = this.current_key || "";
		const [kind_now, name_now] = this.split_key(key);
		const want = { Batch: "", "Work Order": "" };
		if (kind_now) want[kind_now] = name_now;
		const pickers = { Batch: this.batch_field, "Work Order": this.work_order_field };
		Object.entries(pickers).forEach(([kind, field]) => {
			// the server answers with the name as stored: FG10005-001 for fg10005-001
			if (this.same_name(field.get_value(), want[kind])) return;
			const pending = this.syncing[kind];
			pending.push(want[kind]);
			Promise.resolve(field.set_value(want[kind])).finally(() => {
				pending.splice(pending.indexOf(want[kind]), 1);
				if ((this.current_key || "") !== key) this.sync_pickers();
			});
		});
	}

	/** Names as the database compares them: case and trailing spaces ignored. */
	same_name(a, b) {
		return String(a || "").trim().toLowerCase() === String(b || "").trim().toLowerCase();
	}

	/** Take the subject's name as stored when the URL spelled it otherwise
	 *  (case, spaces): replace the URL, so Back does not land on the same
	 *  subject again. */
	adopt_name(kind, asked, stored) {
		// only ever a different spelling of the same name, never another subject
		if (!stored || stored === asked || !this.same_name(stored, asked)) return;
		this.current_key = `${kind}/${stored}`;
		const asked_route = ["quality-explorer", kind, asked].join("/");
		// The address bar may already be on its way elsewhere: the router moves
		// its route only once the next page has loaded, so ask both.
		if (frappe.get_route_str() === asked_route && frappe.router.get_sub_path() === asked_route) {
			frappe.route_flags.replace_route = true;
			this.own_route = `${kind}/${stored}`;
			frappe.set_route("quality-explorer", kind, stored);
			// set_route replaced the URL synchronously, but clears the flag only
			// once the page has settled: left set, the user's next click would
			// replace this entry instead of adding one
			delete frappe.route_flags.replace_route;
		}
	}

	explore(kind, name) {
		const key = `${kind}/${name}`;
		if (key === this.current_key && this.loading) return;
		const seq = (this.seq += 1);
		this.current_key = key;
		this.data = null;
		this.loading = true;
		this.set_tree_buttons(false);
		this.$summary.empty();
		this.$coverage.empty();
		this.$toolbar.empty();
		this.$tree.html(
			'<div class="qe-loading"><span class="qe-spinner"></span> ' + __("Collecting quality records…") + "</div>"
		);

		frappe.call({
			method: QE_METHOD + ".get_quality_records",
			args: kind === "Batch" ? { batch_no: name } : { work_order: name },
			callback: (r) => {
				// the user moved on while this one was loading
				if (seq !== this.seq || !r || !r.message) return;
				this.data = r.message;
				// the URL may have come to spell it otherwise while it loaded
				const asked = this.subject_in_url(kind, name) ?? name;
				this.adopt_name(kind, asked, r.message.subject && r.message.subject.name);
				this.render();
			},
			error: () => {
				if (seq === this.seq) this.show_empty(__("Could not load quality records."));
			},
			always: () => {
				if (seq === this.seq) this.loading = false;
			},
		});
	}

	show_empty(msg) {
		this.data = null;
		this.$summary.empty();
		this.$coverage.empty();
		this.$toolbar.empty();
		this.$tree.html(
			`<div class="qe-empty">
				<div class="qe-empty-icon">${frappe.utils.icon("quality", "lg")}</div>
				<div class="qe-empty-text">${frappe.utils.escape_html(msg)}</div>
			</div>`
		);
		this.set_tree_buttons(false);
	}

	render() {
		const { subject, groups, coverage, summary } = this.data;
		this.$summary.html(this.summary_html(subject, summary));
		this.bind_summary_links(this.$summary);
		this.$coverage.html(this.coverage_html(coverage));
		this.render_toolbar();
		this.render_tree(subject, groups);
		this.set_tree_buttons(true);
		if (!groups.length) [this.expand_btn, this.collapse_btn].forEach((b) => b && b.prop("disabled", true));
	}

	// ---- summary card -------------------------------------------------
	summary_html(subject, summary) {
		const esc = frappe.utils.escape_html;
		const fmt_date = (d) => frappe.datetime.str_to_user(d);
		const is_batch = subject.kind === "Batch";
		const item = [subject.item, subject.item_name !== subject.item ? subject.item_name : null]
			.filter(Boolean)
			.map(esc)
			.join(" · ");

		const facts = [];
		if (is_batch) {
			if (subject.manufacturing_date) facts.push(__("Manufactured {0}", [fmt_date(subject.manufacturing_date)]));
			if (subject.expiry_date) {
				const label = subject.expired ? __("Expired {0}", [fmt_date(subject.expiry_date)]) : __("Expiry {0}", [fmt_date(subject.expiry_date)]);
				facts.push(subject.expired ? `<span class="qe-danger">${label}</span>` : label);
			}
		} else {
			if (subject.status) facts.push(esc(__(subject.status)));
			if (subject.line) facts.push(esc(subject.line));
			const uom = subject.stock_uom ? " " + esc(subject.stock_uom) : "";
			facts.push(__("Produced {0} of {1}", [format_number(flt(subject.produced_qty)), format_number(flt(subject.qty)) + uom]));
		}

		const chips = [];
		if (is_batch && subject.disabled) chips.push(`<span class="qe-chip">${__("Disabled")}</span>`);

		const stat = (value, label, cls = "", title = "") =>
			`<div class="qe-stat" ${title ? `title="${esc(title)}"` : ""}>
				<div class="qe-stat-val ${cls}">${value}</div>
				<div class="qe-stat-lbl">${label}</div>
			</div>`;

		const notes = [];
		if ((summary.hidden || []).length) {
			notes.push(__("Not shown, you may not read them: {0}", [summary.hidden.join(", ")]));
		}
		if (summary.withheld) notes.push(__("{0} records hidden by your permissions", [summary.withheld]));
		if (summary.trace_hint) notes.push(esc(summary.trace_hint));

		const route = is_batch ? ["batch-explorer", subject.name] : ["Form", "Work Order", subject.name];
		const href = is_batch
			? `/app/batch-explorer/${encodeURIComponent(subject.name)}`
			: `/app/work-order/${encodeURIComponent(subject.name)}`;
		const open_link = `<a class="qe-card-link" data-route="${esc(JSON.stringify(route))}" href="${href}">${
			is_batch ? __("Open in Batch Explorer") : __("Open Work Order")
		}</a>`;

		return `
			<div class="qe-card">
				<div class="qe-card-head">
					<div class="qe-card-title">
						<span class="qe-subject-icon">${frappe.utils.icon(is_batch ? "stock" : "tool", "md")}</span>
						<div>
							<div class="qe-subject-kind">${is_batch ? __("Batch") : __("Work Order")}</div>
							<div class="qe-subject-name">${esc(subject.name)}</div>
							<div class="qe-subject-item">${[item, ...facts].filter(Boolean).join(" · ")}</div>
						</div>
					</div>
					${chips.join("")}
				</div>
				<div class="qe-card-stats">
					${stat(summary.records, __("QC Records"))}
					${stat(summary.submitted, __("Submitted"))}
					${stat(summary.drafts, __("Drafts"), summary.drafts ? "qe-warn" : "", __("Not submitted yet"))}
					${stat(summary.failed, __("Failed / Rejected"), summary.failed ? "qe-danger" : "")}
					${stat(summary.work_orders, __("Work Orders"), "", __("Work Orders traced from here, listed under Work Orders below"))}
					${stat(summary.ingredients, __("Ingredient Batches"), "", __("Raw-material batches the Work Orders consumed"))}
				</div>
				<div class="qe-card-foot">
					${open_link}
					${notes.map((n) => `<span class="qe-card-note">${n}</span>`).join("")}
				</div>
			</div>
		`;
	}

	bind_summary_links($root) {
		$root.find(".qe-card-link").on("click", function (e) {
			if (e.ctrlKey || e.metaKey) return; // the browser opens a new tab
			e.preventDefault();
			frappe.set_route(...JSON.parse($(this).attr("data-route")));
		});
	}

	// ---- coverage strip -------------------------------------------------
	coverage_html(coverage) {
		const esc = frappe.utils.escape_html;
		const titles = {
			missing: __("No record"),
			draft: __("Drafts only, nothing submitted"),
			submitted: __("Submitted"),
			failed: __("A record failed or was rejected"),
			hidden: __("You may not read these records"),
		};
		const chips = coverage.map((c) => {
			const withheld = c.withheld ? __("{0} hidden by your permissions", [c.withheld]) : "";
			const title = [titles[c.state], withheld].filter(Boolean).join(" · ");
			let count = c.state === "hidden" ? "—" : c.count;
			if (c.withheld && c.state !== "hidden") count += ` <small>+${c.withheld}</small>`;
			return `
				<div class="qe-cov qe-cov-${c.state}" title="${esc(c.label)}: ${esc(title)}">
					<span class="qe-cov-code">${esc(c.code)}</span>
					<span class="qe-cov-label">${esc(c.label)}</span>
					<span class="qe-cov-count">${count}</span>
				</div>`;
		});
		return `
			<div class="qe-coverage-head">
				<span class="qe-coverage-title">${__("Record coverage")}</span>
				<span class="qe-coverage-legend">
					<span class="qe-legend qe-cov-submitted">${__("Submitted")}</span>
					<span class="qe-legend qe-cov-draft">${__("Drafts only")}</span>
					<span class="qe-legend qe-cov-failed">${__("Failed")}</span>
					<span class="qe-legend qe-cov-missing">${__("No record")}</span>
				</span>
			</div>
			<div class="qe-coverage-grid">${chips.join("")}</div>
		`;
	}

	render_toolbar() {
		const $search = $(`
			<div class="qe-search">
				${frappe.utils.icon("search", "sm")}
				<input type="text" placeholder="${__("Filter records, work orders, batches, inspectors…")}" />
			</div>
		`);
		const self = this;
		$search.find("input").on("input", function () {
			self.filter_text = (this.value || "").toLowerCase();
			self.apply_filter();
		});
		this.filter_text = "";
		this.$toolbar.empty().append($search);
	}

	// ---- tree ---------------------------------------------------------
	render_tree(subject, groups) {
		this.$tree.empty();
		this.build_tree(this.$tree, subject, groups);
	}

	/** Render the whole tree into ``$target``. ``opts.print`` drops the
	 *  interactive bits and leaves every group open. */
	build_tree($target, subject, groups, opts = {}) {
		const $root = $('<div class="qe-root"></div>').appendTo($target);
		const kind = subject.kind === "Batch" ? __("Batch") : __("Work Order");
		$(`
			<div class="qe-root-head">
				<span class="qe-root-dot"></span>
				<span class="qe-root-label">${kind} · ${frappe.utils.escape_html(subject.name)}</span>
			</div>
		`).appendTo($root);

		const $children = $('<div class="qe-children"></div>').appendTo($root);
		const has_records = groups.some((g) => g.code);
		if (!has_records) {
			$(`<div class="qe-none">${__("No quality records found.")}</div>`).appendTo($children);
		}
		// with no records, what they were looked for through is all there is to see
		const group_opts = { ...opts, open_trace: !has_records };
		groups.forEach((group) => this.render_group(group, $children, group_opts));
	}

	render_group(group, $parent, opts = {}) {
		const esc = frappe.utils.escape_html;
		const $group = $('<div class="qe-group"></div>').appendTo($parent);
		// the trace groups explain where the records came from: closed until asked for
		if (group.trace) $group.addClass("qe-trace-group");
		if (group.trace && !opts.print && !opts.open_trace) $group.addClass("qe-collapsed");

		const hint = group.hint ? `<span class="qe-group-hint">${esc(group.hint)}</span>` : "";
		const $head = $(`
			<div class="qe-group-head" style="--qe-color:${group.color}">
				<span class="qe-caret">${frappe.utils.icon("es-line-down", "xs")}</span>
				<span class="qe-group-dot"></span>
				<span class="qe-group-label">${esc(group.label)}</span>
				<span class="qe-badge">${group.count}</span>
				${hint}
			</div>
		`).appendTo($group);

		const $leaves = $('<div class="qe-leaves"></div>').appendTo($group);
		group.nodes.forEach((node) => {
			if (group.code) this.render_record(node, group, $leaves, opts);
			else this.render_trace_leaf(node, group, $leaves, opts);
		});

		if (!opts.print) $head.on("click", () => $group.toggleClass("qe-collapsed"));
	}

	/** One QC record: its result, who inspected it and why it is listed. */
	render_record(node, group, $parent, opts = {}) {
		const esc = frappe.utils.escape_html;
		const meta = [];
		if (node.date) meta.push(frappe.datetime.str_to_user(node.date));
		if (node.shift) meta.push(esc(__(node.shift)));
		if (node.operator) meta.push(`${__("Operator")}: ${esc(node.operator)}`);
		if (node.line) meta.push(esc(node.line));
		if (node.item) meta.push(esc(node.item));
		if (node.batch_no) meta.push(`${__("Batch")} ${esc(node.batch_no)}`);
		if (node.work_order) meta.push(esc(node.work_order));
		if (node.supplier) meta.push(esc(node.supplier));

		const relations = node.relations || [];
		const tags = relations.length
			? `<span class="qe-leaf-tags">${relations.map((r) => this.tag_chip(r.key)).join("")}</span>`
			: "";
		const routes = relations.map((r) => this.relation_note(r)).filter(Boolean);
		const note = routes.length ? `<div class="qe-leaf-note">${routes.map(esc).join(" · ")}</div>` : "";
		const href = `/app/${frappe.router.slug(node.doctype)}/${encodeURIComponent(node.name)}`;
		const inspector = node.inspector
			? `<span class="qe-leaf-user" title="${__("QC Inspector")}: ${esc(node.inspector_name || node.inspector)}">
					${frappe.avatar(node.inspector, "avatar-small")}
					<span class="qe-leaf-user-name">${esc(node.inspector_name || node.inspector)}</span>
				</span>`
			: "";

		const $leaf = $(`
			<div class="qe-leaf" style="--qe-color:${group.color}">
				<span class="qe-leaf-dot"></span>
				<div class="qe-leaf-main">
					<div><span class="qe-leaf-kind">${esc(node.code)}</span><a class="qe-leaf-name" href="${href}">${esc(node.name)}</a>${tags}</div>
					${note}
					<div class="qe-leaf-meta">${meta.join(" · ")}</div>
				</div>
				<div class="qe-leaf-side">
					${this.result_chip(node)}
					${this.status_indicator(node.status, node.docstatus)}
					${inspector}
				</div>
			</div>
		`).appendTo($parent);

		$leaf.attr("data-search", this.haystack(node, group));
		// on paper the hrefs stay, so the PDF links back into the desk
		if (!opts.print) {
			$leaf.find(".qe-leaf-name").on("click", (e) => {
				if (e.ctrlKey || e.metaKey) return; // the browser opens a new tab
				e.preventDefault();
				frappe.set_route("Form", node.doctype, node.name);
			});
		}
	}

	/** A Work Order or batch the records were found through. */
	render_trace_leaf(node, group, $parent, opts = {}) {
		const esc = frappe.utils.escape_html;
		const meta = [];
		if (node.date) meta.push(frappe.datetime.str_to_user(node.date));
		if (node.extra) meta.push(esc(node.extra));
		if (node.tag_detail) meta.push(esc(node.tag_detail));

		const tags = (node.tags || []).length
			? `<span class="qe-leaf-tags">${node.tags.map((t) => this.tag_chip(t)).join("")}</span>`
			: "";
		const kind = node.doctype === "Batch" ? __("Batch No") : __(node.doctype);
		const href = "/app/" + node.route.map((p) => encodeURIComponent(p)).join("/");
		const qty = node.qty != null
			? `<span class="qe-qty">${format_number(node.qty)}${node.uom ? `<small>${esc(node.uom)}</small>` : ""}</span>`
			: "";
		const n = node.qc_count || 0;
		const withheld = node.qc_withheld || 0;
		// records the user may not see are there all the same: never a bare "0"
		const hidden_note = withheld
			? ` <small title="${__("Hidden by your permissions")}">+${__("{0} hidden", [withheld])}</small>`
			: "";
		const count = `<span class="qe-qc-count ${n || withheld ? "" : "qe-qc-count-none"}">${
			n === 1 ? __("1 QC record") : __("{0} QC records", [n])
		}${hidden_note}</span>`;

		const $leaf = $(`
			<div class="qe-leaf" style="--qe-color:${group.color}">
				<span class="qe-leaf-dot"></span>
				<div class="qe-leaf-main">
					<div><span class="qe-leaf-kind">${esc(kind)}</span><a class="qe-leaf-name" href="${href}">${esc(node.name)}</a>${tags}</div>
					<div class="qe-leaf-meta">${meta.join(" · ")}</div>
				</div>
				<div class="qe-leaf-side">
					${qty}
					${count}
					${this.status_indicator(node.status, node.docstatus)}
				</div>
			</div>
		`).appendTo($parent);

		$leaf.attr("data-search", this.haystack(node, group));
		if (!opts.print) {
			// explore that Work Order or batch in its turn
			$leaf.find(".qe-leaf-name").on("click", (e) => {
				if (e.ctrlKey || e.metaKey) return; // the browser opens a new tab
				e.preventDefault();
				frappe.set_route(...node.route);
			});
		}
	}

	tag_label(key) {
		const labels = {
			this_batch: __("This batch"),
			output_batch: __("Batch produced"),
			work_order: __("Work Order"),
			this_work_order: __("This Work Order"),
			ingredient: __("Ingredient"),
			semi_finished: __("Semi-finished run"),
			produced: __("Made this batch"),
			named_on_record: __("Named on a QC record"),
			no_receiving_record: __("No receiving record"),
		};
		return labels[key] || key;
	}

	tag_chip(key) {
		const warn = key === "no_receiving_record";
		return `<span class="qe-chip qe-leaf-tag ${warn ? "qe-tag-warn" : ""}">${frappe.utils.escape_html(this.tag_label(key))}</span>`;
	}

	/** The route behind a relation where neither its chip nor the record's own
	 *  batch and Work Order (on the meta line) say it. */
	relation_note(rel) {
		return rel.key === "ingredient" || rel.key === "semi_finished" ? rel.detail : null;
	}

	result_chip(node) {
		if (!node.result) return `<span class="qe-result qe-result-none">${__("No result")}</span>`;
		const cls = { pass: "qe-result-pass", warn: "qe-result-warn", fail: "qe-result-fail" }[node.result_level] || "";
		return `<span class="qe-result ${cls}">${frappe.utils.escape_html(__(node.result))}</span>`;
	}

	status_indicator(status, docstatus) {
		if (!status) return "";
		const map = {
			Draft: "gray",
			Submitted: "blue",
			Cancelled: "red",
			Completed: "green",
			"Not Started": "orange",
			"In Process": "orange",
			Closed: "green",
			Stopped: "red",
		};
		const color = map[status] || (docstatus === 2 ? "red" : docstatus === 1 ? "blue" : "gray");
		return `<span class="qe-status indicator-pill ${color}">${frappe.utils.escape_html(__(status))}</span>`;
	}

	haystack(node, group) {
		const bits = [
			node.name,
			node.code,
			node.date,
			node.shift,
			node.line,
			node.item,
			node.batch_no,
			node.work_order,
			node.supplier,
			node.operator,
			node.inspector_name,
			node.result,
			node.status,
			node.extra,
			node.tag_detail,
			group.label,
		];
		(node.relations || []).forEach((r) => bits.push(this.tag_label(r.key), r.detail));
		(node.tags || []).forEach((t) => bits.push(this.tag_label(t)));
		return bits.filter(Boolean).join(" ").toLowerCase();
	}

	// ---- save as PDF --------------------------------------------------
	/** Print the exploration, fully expanded: the quality dossier of a batch
	 *  or a Work Order for an audit. Built off-screen from the data, so the
	 *  filter and whatever the user has collapsed never reach the paper; the
	 *  browser's "Save as PDF" destination writes the file. */
	save_pdf() {
		if (!this.data) {
			frappe.show_alert({ message: __("Explore a batch or a work order first"), indicator: "orange" });
			return;
		}
		const { subject, groups, coverage, summary } = this.data;
		$(".qe-print-doc").remove();

		const $doc = $('<div class="qe-print-doc" aria-hidden="true"></div>').appendTo(document.body);
		$doc.append(this.print_header_html(subject));
		const $body = $('<div class="qe-container"></div>').appendTo($doc);
		$('<div class="qe-summary"></div>').appendTo($body).html(this.summary_html(subject, summary));
		$('<div class="qe-coverage"></div>').appendTo($body).html(this.coverage_html(coverage));
		this.build_tree($('<div class="qe-tree"></div>').appendTo($body), subject, groups, { print: true });

		// the title is the name the browser offers for the saved file
		const title = document.title;
		const print_title = `${__("Quality Explorer")} - ${subject.name}`;
		document.title = print_title;
		document.documentElement.classList.add("qe-printing");

		const mql = window.matchMedia ? window.matchMedia("print") : null;
		let cleaned = false;
		const cleanup = () => {
			if (cleaned) return;
			cleaned = true;
			window.removeEventListener("afterprint", cleanup);
			if (mql && mql.removeEventListener) mql.removeEventListener("change", on_print_media);
			document.documentElement.classList.remove("qe-printing");
			// the router may have retitled the page while the dialog was open
			if (document.title === print_title) document.title = title;
			$doc.remove();
		};
		const on_print_media = (e) => {
			if (!e.matches) cleanup();
		};

		window.addEventListener("afterprint", cleanup);
		if (mql && mql.addEventListener) mql.addEventListener("change", on_print_media);
		// last resort, for a browser that fires neither
		setTimeout(cleanup, 60000);

		// two frames, so the off-screen copy is laid out and painted, and its
		// avatars fetched, before the browser snapshots the page
		requestAnimationFrame(() => requestAnimationFrame(() => window.print()));
	}

	print_header_html(subject) {
		const esc = frappe.utils.escape_html;
		const company = (frappe.defaults && frappe.defaults.get_default("company")) || "";
		const who = frappe.session.user_fullname || frappe.session.user || "";
		const when = frappe.datetime.str_to_user(frappe.datetime.now_datetime());
		const kind = subject.kind === "Batch" ? __("Batch") : __("Work Order");
		const item = [subject.item, subject.item_name].filter(Boolean).map(esc).join(" · ");

		return `
			<div class="qe-print-head">
				<div>
					<div class="qe-print-title">${__("Quality Records")} · ${kind} ${esc(subject.name)}</div>
					<div class="qe-print-sub">${item}</div>
				</div>
				<div class="qe-print-meta">
					${company ? esc(company) + "<br>" : ""}
					${__("Generated {0} by {1}", [esc(when), esc(who)])}
				</div>
			</div>
		`;
	}

	// ---- interactions -------------------------------------------------
	toggle_all(expand) {
		this.$tree.find(".qe-group").toggleClass("qe-collapsed", !expand);
	}

	apply_filter() {
		const q = this.filter_text;
		this.$tree.find(".qe-leaf").each(function () {
			const hay = $(this).attr("data-search") || "";
			$(this).toggle(!q || hay.indexOf(q) !== -1);
		});
		// while filtering, show and open every group that holds a match; a
		// collapsed group hides its leaves, so count what the filter kept
		// rather than what is on screen
		this.$tree.find(".qe-group").each(function () {
			const kept = $(this)
				.find(".qe-leaf")
				.filter(function () {
					return this.style.display !== "none";
				}).length;
			$(this).toggle(!q || kept > 0);
			if (q && kept > 0) $(this).removeClass("qe-collapsed");
		});
	}
};
