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

isnack.BatchExplorer = class BatchExplorer {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.filter_text = "";
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
		this.batch_field.set_value(batch);
		this.explore(batch);
	}

	explore(batch) {
		this.current_batch = batch;
		this.set_tree_buttons(false);
		this.$summary.empty();
		this.$toolbar.empty();
		this.$tree.html('<div class="be-loading"><span class="be-spinner"></span> ' + __("Tracing batch…") + "</div>");

		frappe.call({
			method: "isnack.isnack.page.batch_explorer.batch_explorer.get_batch_usage",
			args: { batch_no: batch },
			callback: (r) => {
				if (!r || !r.message) return;
				this.data = r.message;
				this.render();
			},
			error: () => this.show_empty(__("Could not load batch usage.")),
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
		const expiry_cls = batch.expired ? "be-chip danger" : "be-chip";
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
				<input type="text" placeholder="${__("Filter documents, users, status…")}" />
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

		const total = group.total_qty != null
			? `<span class="be-group-qty">${format_number(group.total_qty)}</span>`
			: "";

		const $head = $(`
			<div class="be-group-head" style="--be-color:${group.color}">
				<span class="be-caret">${frappe.utils.icon("es-line-down", "xs")}</span>
				<span class="be-group-dot"></span>
				<span class="be-group-label">${frappe.utils.escape_html(group.label)}</span>
				<span class="be-badge">${group.count}</span>
				${total}
			</div>
		`).appendTo($group);

		const $leaves = $('<div class="be-leaves"></div>').appendTo($group);
		group.nodes.forEach((node) => this.render_leaf(node, group, $leaves));

		$head.on("click", () => $group.toggleClass("be-collapsed"));
	}

	render_leaf(node, group, $parent) {
		const status = this.status_indicator(node);
		let qty = "";
		if (node.qty != null && node.direction) {
			const cls = node.direction === "in" ? "be-in" : "be-out";
			const sign = node.direction === "in" ? "+" : "";
			qty = `<span class="be-qty ${cls}">${sign}${format_number(node.qty)}</span>`;
		}
		const meta_bits = [];
		if (node.date) meta_bits.push(frappe.datetime.str_to_user(node.date));
		if (node.party) meta_bits.push(frappe.utils.escape_html(node.party));
		if (node.extra) meta_bits.push(frappe.utils.escape_html(node.extra));

		const $leaf = $(`
			<div class="be-leaf" style="--be-color:${group.color}">
				<span class="be-leaf-dot"></span>
				<div class="be-leaf-main">
					<a class="be-leaf-name" href="/app/${frappe.router.slug(node.doctype)}/${encodeURIComponent(node.name)}">
						${frappe.utils.escape_html(node.name)}
					</a>
					<div class="be-leaf-meta">${meta_bits.join(" · ")}</div>
				</div>
				<div class="be-leaf-side">
					${qty}
					${status}
					<span class="be-leaf-user" title="${__("Created by")} ${frappe.utils.escape_html(node.owner_name || "")}">
						${frappe.avatar(node.owner, "avatar-small")}
						<span class="be-leaf-user-name">${frappe.utils.escape_html(node.owner_name || "")}</span>
					</span>
				</div>
			</div>
		`).appendTo($parent);

		// searchable haystack
		$leaf.attr(
			"data-search",
			[node.name, node.owner_name, node.status, node.party, node.extra, group.label]
				.filter(Boolean)
				.join(" ")
				.toLowerCase()
		);

		$leaf.find(".be-leaf-name").on("click", (e) => {
			e.preventDefault();
			frappe.set_route("Form", node.doctype, node.name);
		});
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
			$(this).toggle(!q || hay.indexOf(q) !== -1);
		});
		// hide groups with no visible leaves while filtering
		this.$tree.find(".be-group").each(function () {
			const visible = $(this).find(".be-leaf:visible").length;
			$(this).toggle(!q || visible > 0);
			if (q && visible > 0) $(this).removeClass("be-collapsed");
		});
	}
};
