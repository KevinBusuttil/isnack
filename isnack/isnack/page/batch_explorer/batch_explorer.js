frappe.provide("isnack");

frappe.pages["batch-explorer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Batch Explorer"),
		single_column: true,
	});
	wrapper.batch_explorer = new isnack.BatchExplorer(page);
};

frappe.pages["batch-explorer"].on_page_show = function (wrapper) {
	// Support deep links: /app/batch-explorer/<batch-id>
	const route = frappe.get_route();
	if (route && route.length > 1 && wrapper.batch_explorer) {
		wrapper.batch_explorer.load_from_route(route.slice(1).join("/"));
	}
};

const BE_METHOD = "isnack.isnack.page.batch_explorer.batch_explorer";

isnack.BatchExplorer = class BatchExplorer {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.filter_text = "";
		this.loading = false;
		this.make();
	}

	make() {
		this.controls();
		this.layout();
		this.show_empty(__("Select a batch to explore its journey through the system."));
	}

	controls() {
		this.batch_field = this.page.add_field({
			fieldname: "batch",
			label: __("Batch"),
			fieldtype: "Link",
			options: "Batch",
			change: () => {
				const v = this.batch_field.get_value();
				if (v) this.explore(v);
			},
		});

		this.page.set_primary_action(
			__("Explore"),
			() => {
				const v = this.batch_field.get_value();
				if (v) this.explore(v);
				else frappe.show_alert({ message: __("Please pick a batch"), indicator: "orange" });
			},
			"search"
		);

		this.expand_btn = this.page.add_button(__("Expand all"), () => this.toggle_all(true));
		this.collapse_btn = this.page.add_button(__("Collapse all"), () => this.toggle_all(false));
		this.set_tree_buttons(false);
	}

	set_tree_buttons(enabled) {
		[this.expand_btn, this.collapse_btn].forEach((b) => b && b.prop("disabled", !enabled));
	}

	layout() {
		this.body = $('<div class="be-container"></div>').appendTo(this.page.main);
		this.$summary = $('<div class="be-summary"></div>').appendTo(this.body);
		this.$toolbar = $('<div class="be-toolbar"></div>').appendTo(this.body);
		this.$tree = $('<div class="be-tree"></div>').appendTo(this.body);
	}

	load_from_route(batch) {
		if (!batch || batch === this.current_batch) return;
		// set_value fires the field's change handler, which already explores;
		// the explicit call below only runs when it did not.
		this.batch_field.set_value(batch);
		if (batch !== this.current_batch) this.explore(batch);
	}

	explore(batch) {
		if (batch === this.current_batch && this.loading) return;
		this.current_batch = batch;
		this.loading = true;
		this.set_tree_buttons(false);
		this.$summary.empty();
		this.$toolbar.empty();
		this.$tree.html('<div class="be-loading"><span class="be-spinner"></span> ' + __("Tracing batch…") + "</div>");

		frappe.call({
			method: BE_METHOD + ".get_batch_usage",
			args: { batch_no: batch },
			callback: (r) => {
				if (!r || !r.message) return;
				this.data = r.message;
				this.render();
			},
			error: () => this.show_empty(__("Could not load batch usage.")),
			always: () => {
				this.loading = false;
			},
		});
	}

	show_empty(msg) {
		this.$summary.empty();
		this.$toolbar.empty();
		this.$tree.html(
			`<div class="be-empty">
				<div class="be-empty-icon">${frappe.utils.icon("tree", "lg")}</div>
				<div class="be-empty-text">${frappe.utils.escape_html(msg)}</div>
			</div>`
		);
		this.set_tree_buttons(false);
	}

	render() {
		const { batch, groups, summary } = this.data;
		this.render_summary(batch, summary);
		this.render_toolbar();
		this.render_tree(batch, groups);
		this.set_tree_buttons(groups.length > 0);
	}

	// ---- summary card -------------------------------------------------
	render_summary(batch, summary) {
		const fmt_date = (d) => (d ? frappe.datetime.str_to_user(d) : "—");
		const expiry_lbl = batch.expired ? __("Expired") : __("Expiry");

		this.$summary.html(`
			<div class="be-card">
				<div class="be-card-head">
					<div class="be-card-title">
						<span class="be-batch-icon">${frappe.utils.icon("package", "md")}</span>
						<div>
							<div class="be-batch-name">${frappe.utils.escape_html(batch.name)}</div>
							<div class="be-batch-item">
								${frappe.utils.escape_html(batch.item || "")}
								${batch.item_name ? "· " + frappe.utils.escape_html(batch.item_name) : ""}
							</div>
						</div>
					</div>
					${batch.disabled ? '<span class="be-chip muted">' + __("Disabled") + "</span>" : ""}
				</div>
				<div class="be-card-stats">
					<div class="be-stat">
						<div class="be-stat-val">${format_number(flt(batch.batch_qty))} <small>${frappe.utils.escape_html(batch.stock_uom || "")}</small></div>
						<div class="be-stat-lbl">${__("Batch Qty")}</div>
					</div>
					<div class="be-stat">
						<div class="be-stat-val">${fmt_date(batch.manufacturing_date)}</div>
						<div class="be-stat-lbl">${__("Manufactured")}</div>
					</div>
					<div class="be-stat">
						<div class="be-stat-val ${batch.expired ? "be-danger" : ""}">${fmt_date(batch.expiry_date)}</div>
						<div class="be-stat-lbl">${expiry_lbl}</div>
					</div>
					<div class="be-stat">
						<div class="be-stat-val">${summary.transactions}</div>
						<div class="be-stat-lbl">${__("Transactions")}</div>
					</div>
					<div class="be-stat">
						<div class="be-stat-val">${summary.doctypes}</div>
						<div class="be-stat-lbl">${__("Document Types")}</div>
					</div>
				</div>
				<div class="be-card-foot">
					${frappe.avatar(batch.owner, "avatar-small")}
					<span>${__("Created by")} <b>${frappe.utils.escape_html(batch.owner_name || batch.owner || "")}</b></span>
				</div>
			</div>
		`);
	}

	render_toolbar() {
		const $search = $(`
			<div class="be-search">
				${frappe.utils.icon("search", "sm")}
				<input type="text" placeholder="${__("Filter documents, users, status, materials…")}" />
			</div>
		`);
		const self = this;
		$search.find("input").on("input", function () {
			self.filter_text = (this.value || "").toLowerCase();
			self.apply_filter();
		});
		this.$toolbar.append($search);
	}

	// ---- tree ---------------------------------------------------------
	render_tree(batch, groups) {
		this.$tree.empty();
		if (!groups.length) {
			this.show_empty(__("This batch has not been used in any transaction yet."));
			return;
		}

		const $root = $('<div class="be-node be-root"></div>').appendTo(this.$tree);
		$(`
			<div class="be-root-head">
				<span class="be-root-dot"></span>
				<span class="be-root-label">${__("Batch")} · ${frappe.utils.escape_html(batch.name)}</span>
			</div>
		`).appendTo($root);

		const $children = $('<div class="be-children"></div>').appendTo($root);

		groups.forEach((group) => this.render_group(group, $children));
	}

	render_group(group, $parent) {
		const $group = $('<div class="be-group"></div>').appendTo($parent);
		// nested (production input) groups start collapsed
		if (group.sub) $group.addClass("be-sub-group be-collapsed");

		const total = group.total_qty != null
			? `<span class="be-group-qty">${format_number(group.total_qty)}</span>`
			: "";
		const hint = group.hint
			? `<span class="be-group-hint">${frappe.utils.escape_html(group.hint)}</span>`
			: "";

		const $head = $(`
			<div class="be-group-head" style="--be-color:${group.color}">
				<span class="be-caret">${frappe.utils.icon("es-line-down", "xs")}</span>
				<span class="be-group-dot"></span>
				<span class="be-group-label">${frappe.utils.escape_html(group.label)}</span>
				<span class="be-badge">${group.count}</span>
				${hint}
				${total}
			</div>
		`).appendTo($group);

		const $leaves = $('<div class="be-leaves"></div>').appendTo($group);
		group.nodes.forEach((node) => this.render_leaf(node, group, $leaves));

		$head.on("click", () => $group.toggleClass("be-collapsed"));
	}

	render_leaf(node, group, $parent) {
		const esc = frappe.utils.escape_html;
		const status = this.status_indicator(node);
		const qty = this.qty_chip(node);

		const meta_bits = [];
		if (node.date) meta_bits.push(frappe.datetime.str_to_user(node.date));
		if (node.party) meta_bits.push(esc(node.party));
		if (node.extra) meta_bits.push(esc(node.extra));
		if (node.tag_detail) meta_bits.push(esc(node.tag_detail));

		const tags = (node.tags || []).length
			? `<span class="be-leaf-tags">${node.tags.map((t) => this.tag_chip(t)).join("")}</span>`
			: "";
		const note = node.lineage ? `<div class="be-leaf-note">${this.lineage_note(node.lineage)}</div>` : "";
		const lines = (node.lines || []).length ? this.lines_html(node.lines) : "";
		const user = node.owner
			? `<span class="be-leaf-user" title="${__("Created by")} ${esc(node.owner_name || "")}">
					${frappe.avatar(node.owner, "avatar-small")}
					<span class="be-leaf-user-name">${esc(node.owner_name || "")}</span>
				</span>`
			: "";

		// route === null means "no link" (e.g. the batch being explored itself)
		const has_link = node.route !== null;
		const href = node.route
			? this.route_href(node.route)
			: `/app/${frappe.router.slug(node.doctype)}/${encodeURIComponent(node.name)}`;
		const name_html = has_link
			? `<a class="be-leaf-name" href="${href}">${esc(node.name)}</a>`
			: `<span class="be-leaf-name be-leaf-name-static">${esc(node.name)}</span>`;

		const $leaf = $(`
			<div class="be-leaf" style="--be-color:${group.color}">
				<span class="be-leaf-dot"></span>
				<div class="be-leaf-main">
					<div>${name_html}${tags}</div>
					${note}
					<div class="be-leaf-meta">${meta_bits.join(" · ")}</div>
					${lines}
				</div>
				<div class="be-leaf-side">
					${qty}
					${status}
					${user}
				</div>
			</div>
		`).appendTo($parent);

		$leaf.attr("data-name", node.name);
		// searchable haystack (includes the nested production inputs)
		$leaf.attr("data-search", this.haystack(node, group));

		if (has_link) {
			$leaf.find(".be-leaf-name").on("click", (e) => {
				e.preventDefault();
				if (node.route) frappe.set_route(...node.route);
				else frappe.set_route("Form", node.doctype, node.name);
			});
		}
		$leaf.find(".be-leaf-lines a").on("click", function (e) {
			e.preventDefault();
			frappe.set_route("Form", "Stock Entry", $(this).attr("data-name"));
		});

		if (node.children && node.children.length) {
			const $sub = $('<div class="be-sub"></div>').appendTo($parent);
			node.children.forEach((child) => this.render_group(child, $sub));
		} else if (node.inputs_deferred) {
			this.render_deferred(node, $parent);
		}
		return $leaf;
	}

	render_deferred(node, $parent) {
		const label = __("Load production inputs");
		const $btn = $(`<button class="btn btn-xs btn-default be-load-inputs">${label}</button>`).appendTo($parent);
		$btn.on("click", () => {
			$btn.prop("disabled", true).text(__("Loading…"));
			frappe.call({
				method: BE_METHOD + ".get_work_order_inputs",
				args: { work_order: node.name, batch_no: this.current_batch },
				callback: (r) => {
					Object.assign(node, r.message || {});
					node.inputs_deferred = false;
					this.render_tree(this.data.batch, this.data.groups);
					this.apply_filter();
					// open what was just loaded
					this.$tree
						.find(".be-leaf")
						.filter(function () {
							return $(this).attr("data-name") === node.name;
						})
						.next(".be-sub")
						.find(".be-group")
						.removeClass("be-collapsed");
				},
				error: () => $btn.prop("disabled", false).text(label),
			});
		});
	}

	route_href(route) {
		if (route[0] === "Form" && route.length >= 3) {
			return `/app/${frappe.router.slug(route[1])}/${encodeURIComponent(route[2])}`;
		}
		return "/app/" + route.map((p) => encodeURIComponent(p)).join("/");
	}

	qty_chip(node) {
		if (node.qty == null) return "";
		if (node.neutral) {
			const uom = node.uom ? `<small class="be-qty-uom">${frappe.utils.escape_html(node.uom)}</small>` : "";
			return `<span class="be-qty be-qty-neutral">${format_number(node.qty)}${uom}</span>`;
		}
		if (!node.direction) return "";
		const cls = node.direction === "in" ? "be-in" : "be-out";
		const sign = node.direction === "in" ? "+" : "";
		return `<span class="be-qty ${cls}">${sign}${format_number(node.qty)}</span>`;
	}

	tag_label(key) {
		const labels = {
			consumed: __("Consumed"),
			produced: __("Produced"),
			this_batch: __("This batch"),
			no_batch: __("No batch · trace ends here"),
			expired: __("Expired"),
			disabled: __("Disabled"),
			shared_output: __("Shared output"),
			multi_level_bom: __("Multi-level BOM"),
			manufacture: __("Manufacture"),
			consumption: __("Consumption"),
			to_wip: __("To WIP"),
			return_erpnext: __("Return (ERPNext)"),
			return: __("Return"),
			mr_fulfilment: __("MR fulfilment"),
			staging: __("Staging"),
			surplus_staged: __("Surplus staged"),
			surplus_swept: __("Surplus swept"),
			transfer: __("Transfer"),
		};
		return labels[key] || key;
	}

	tag_chip(key) {
		const warn = ["shared_output", "expired", "disabled", "no_batch"].includes(key);
		return `<span class="be-chip muted be-leaf-tag ${warn ? "be-tag-warn" : ""}">${frappe.utils.escape_html(this.tag_label(key))}</span>`;
	}

	lineage_note(l) {
		const uom = l.uom ? " " + frappe.utils.escape_html(l.uom) : "";
		let first = __("This batch") + ": " + format_number(l.this_batch) + uom;
		if (l.scrap) first += " (+" + format_number(l.scrap) + " " + __("scrap") + ")";
		const parts = [first, __("Work Order output") + ": " + format_number(l.total) + uom];
		if (l.share != null) parts.push(Math.round(l.share * 1000) / 10 + " %");
		if (l.hidden_entries) parts.push(__("{0} entries hidden by permissions", [l.hidden_entries]));
		return parts.join(" · ");
	}

	lines_html(lines) {
		const esc = frappe.utils.escape_html;
		const items = lines.map((ln) => {
			const bits = [
				`<a href="/app/stock-entry/${encodeURIComponent(ln.stock_entry)}" data-name="${esc(ln.stock_entry)}">${esc(ln.stock_entry)}</a>`,
			];
			if (ln.purpose) bits.push(esc(ln.purpose));
			if (ln.date) bits.push(frappe.datetime.str_to_user(ln.date));
			if (ln.warehouse) bits.push(esc(ln.warehouse));
			if (ln.qty != null) bits.push(format_number(ln.qty));
			if (ln.split) bits.push(__("bundle {0}", [esc(ln.split)]));
			return `<li>${bits.join(" · ")}</li>`;
		});
		return `<ul class="be-leaf-lines">${items.join("")}</ul>`;
	}

	haystack(node, group) {
		const bits = [
			node.name,
			node.owner_name,
			node.status,
			node.party,
			node.extra,
			node.item_code,
			node.tag_detail,
			group.label,
		];
		(node.tags || []).forEach((t) => bits.push(this.tag_label(t)));
		(node.lines || []).forEach((ln) => bits.push(ln.stock_entry));
		(node.children || []).forEach((child) =>
			(child.nodes || []).forEach((n) => bits.push(this.haystack(n, child)))
		);
		return bits.filter(Boolean).join(" ").toLowerCase();
	}

	status_indicator(node) {
		const map = {
			Draft: "gray",
			Submitted: "blue",
			Cancelled: "red",
			Completed: "green",
			"Not Started": "orange",
			"In Process": "orange",
			Paid: "green",
			"To Bill": "orange",
			"To Deliver": "orange",
			Closed: "green",
			Stopped: "red",
			Return: "gray",
		};
		const color = map[node.status] || (node.docstatus === 2 ? "red" : node.docstatus === 1 ? "blue" : "gray");
		if (!node.status) return "";
		return `<span class="be-status indicator-pill ${color}">${frappe.utils.escape_html(node.status)}</span>`;
	}

	// ---- interactions -------------------------------------------------
	toggle_all(expand) {
		this.$tree.find(".be-group").toggleClass("be-collapsed", !expand);
	}

	apply_filter() {
		const q = this.filter_text;
		this.$tree.find(".be-leaf").each(function () {
			const hay = $(this).attr("data-search") || "";
			const show = !q || hay.indexOf(q) !== -1;
			$(this).toggle(show);
			// a Work Order's nested inputs follow their leaf
			$(this).next(".be-sub, .be-load-inputs").toggle(show);
		});
		// hide groups with no visible leaves while filtering
		this.$tree.find(".be-group").each(function () {
			const visible = $(this).find(".be-leaf:visible").length;
			$(this).toggle(!q || visible > 0);
			if (q && visible > 0) $(this).removeClass("be-collapsed");
		});
	}
};
