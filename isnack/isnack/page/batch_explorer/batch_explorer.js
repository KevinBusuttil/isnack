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
		this.pdf_btn = this.page.add_button(__("Save as PDF"), () => this.save_pdf());
		this.set_tree_buttons(false);
	}

	set_tree_buttons(enabled) {
		[this.expand_btn, this.collapse_btn, this.pdf_btn].forEach(
			(b) => b && b.prop("disabled", !enabled)
		);
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
		this.$summary.html(this.summary_html(batch, summary));
	}

	summary_html(batch, summary) {
		const fmt_date = (d) => (d ? frappe.datetime.str_to_user(d) : "—");
		const expiry_lbl = batch.expired ? __("Expired") : __("Expiry");

		return `
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
		`;
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
		this.build_tree(this.$tree, batch, groups);
	}

	/** Render the whole tree into ``$target``. ``opts.print`` drops the
	 *  interactive bits and leaves every group open. */
	build_tree($target, batch, groups, opts = {}) {
		const $root = $('<div class="be-node be-root"></div>').appendTo($target);
		$(`
			<div class="be-root-head">
				<span class="be-root-dot"></span>
				<span class="be-root-label">${__("Batch")} · ${frappe.utils.escape_html(batch.name)}</span>
			</div>
		`).appendTo($root);

		const $children = $('<div class="be-children"></div>').appendTo($root);

		groups.forEach((group) => this.render_group(group, $children, opts));
	}

	render_group(group, $parent, opts = {}) {
		const $group = $('<div class="be-group"></div>').appendTo($parent);
		// nested (production input) groups start collapsed, except on paper
		if (group.sub) $group.addClass("be-sub-group");
		if (group.sub && !opts.print) $group.addClass("be-collapsed");

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
		group.nodes.forEach((node) => this.render_leaf(node, group, $leaves, opts));

		if (!opts.print) $head.on("click", () => $group.toggleClass("be-collapsed"));
	}

	render_leaf(node, group, $parent, opts = {}) {
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
		const note_html = node.lineage ? this.lineage_note(node.lineage) : node.made ? this.made_note(node.made) : "";
		const note = note_html ? `<div class="be-leaf-note">${note_html}</div>` : "";
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
		const kind = this.kind_label(node);
		const kind_html = kind ? `<span class="be-leaf-kind">${esc(kind)}</span>` : "";

		const $leaf = $(`
			<div class="be-leaf" style="--be-color:${group.color}">
				<span class="be-leaf-dot"></span>
				<div class="be-leaf-main">
					<div>${kind_html}${name_html}${tags}</div>
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

		// on paper the hrefs stay, so the PDF links back into the desk
		if (has_link && !opts.print) {
			$leaf.find(".be-leaf-name").on("click", (e) => {
				e.preventDefault();
				if (node.route) frappe.set_route(...node.route);
				else frappe.set_route("Form", node.doctype, node.name);
			});
		}
		if (!opts.print) {
			$leaf.find(".be-leaf-lines a").on("click", function (e) {
				e.preventDefault();
				frappe.set_route("Form", "Stock Entry", $(this).attr("data-name"));
			});
		}

		if (node.children && node.children.length) {
			const $sub = $('<div class="be-sub"></div>').appendTo($parent);
			node.children.forEach((child) => this.render_group(child, $sub, opts));
		} else if (node.inputs_deferred) {
			if (opts.print) {
				$(`<div class="be-print-note">${__("Production inputs could not be loaded.")}</div>`).appendTo(
					$parent
				);
			} else {
				this.render_deferred(node, $parent);
			}
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

	/** What the row's ID is, shown in front of it: the document type, with
	 *  "Batch No" for a lot. A material without a batch is an "Item". */
	kind_label(node) {
		if (node.doctype === "Batch") return __("Batch No");
		return node.doctype ? __(node.doctype) : "";
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
			semi_finished: __("Semi-finished"),
			other_source: __("Origin not recorded"),
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
		const warn = ["shared_output", "expired", "disabled", "no_batch", "other_source"].includes(key);
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

	made_note(made) {
		const uom = made.uom ? " " + frappe.utils.escape_html(made.uom) : "";
		return __("Made {0}", [format_number(made.qty) + uom]);
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

	// ---- save as PDF --------------------------------------------------
	/** Print the whole exploration of the selected batch, fully expanded.
	 *
	 *  The document is built off-screen from the data rather than from the tree
	 *  on screen, so the filter and whatever the user has collapsed never reach
	 *  the paper, and the page itself is left exactly as it was. Printing it
	 *  keeps the page's own stylesheet, so the colours survive; the browser's
	 *  "Save as PDF" destination writes the file.
	 */
	save_pdf() {
		if (!this.data || !(this.data.groups || []).length) {
			frappe.show_alert({ message: __("Explore a batch first"), indicator: "orange" });
			return;
		}
		if (this.preparing_pdf) return;
		this.preparing_pdf = true;

		const batch = this.current_batch;
		const label = __("Save as PDF");
		if (this.pdf_btn) this.pdf_btn.prop("disabled", true).text(__("Preparing…"));

		const done = () => {
			this.preparing_pdf = false;
			if (!this.pdf_btn) return;
			this.pdf_btn.text(label);
			this.pdf_btn.prop("disabled", this.loading || !(this.data && (this.data.groups || []).length));
		};

		this.full_data()
			.then((data) => {
				// the user moved on to another batch while we were loading
				if (batch === this.current_batch) this.print_document(data);
			})
			.catch(() => frappe.show_alert({ message: __("Could not prepare the PDF."), indicator: "red" }))
			.then(done, done);
	}

	/** The exploration with every producing Work Order's inputs loaded, so that
	 *  nothing is left behind a "Load production inputs" button on paper. */
	full_data() {
		const deferred = (this.data.groups || []).some((g) =>
			(g.nodes || []).some((n) => n.inputs_deferred)
		);
		if (!deferred) return Promise.resolve(this.data);

		const fallback = this.data;
		return frappe
			.call({
				method: BE_METHOD + ".get_batch_usage",
				args: { batch_no: this.current_batch, eager_inputs: 1 },
			})
			.then((r) => (r && r.message) || fallback)
			.catch(() => {
				// still worth a PDF: the Work Orders that stay deferred say so on paper
				frappe.show_alert({
					message: __("Some production inputs could not be loaded."),
					indicator: "orange",
				});
				return fallback;
			});
	}

	print_document(data) {
		const { batch, groups, summary } = data;
		$(".be-print-doc").remove();

		const $doc = $('<div class="be-print-doc" aria-hidden="true"></div>').appendTo(document.body);
		$doc.append(this.print_header_html(batch));
		const $body = $('<div class="be-container"></div>').appendTo($doc);
		$('<div class="be-summary"></div>').appendTo($body).html(this.summary_html(batch, summary));
		this.build_tree($('<div class="be-tree"></div>').appendTo($body), batch, groups, { print: true });

		// the title is the name the browser offers for the saved file
		const title = document.title;
		const print_title = `${__("Batch Explorer")} - ${batch.name}`;
		document.title = print_title;
		document.documentElement.classList.add("be-printing");

		const mql = window.matchMedia ? window.matchMedia("print") : null;
		let cleaned = false;
		const cleanup = () => {
			if (cleaned) return;
			cleaned = true;
			window.removeEventListener("afterprint", cleanup);
			if (mql && mql.removeEventListener) mql.removeEventListener("change", on_print_media);
			document.documentElement.classList.remove("be-printing");
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

		// two frames, so the off-screen copy is laid out and painted — and its
		// avatars fetched — before the browser snapshots the page
		requestAnimationFrame(() => requestAnimationFrame(() => window.print()));
	}

	print_header_html(batch) {
		const esc = frappe.utils.escape_html;
		const company = (frappe.defaults && frappe.defaults.get_default("company")) || "";
		const who = frappe.session.user_fullname || frappe.session.user || "";
		const when = frappe.datetime.str_to_user(frappe.datetime.now_datetime());
		const item = [batch.item, batch.item_name].filter(Boolean).map(esc).join(" · ");

		return `
			<div class="be-print-head">
				<div>
					<div class="be-print-title">${__("Batch Explorer")} · ${esc(batch.name)}</div>
					<div class="be-print-sub">${item}</div>
				</div>
				<div class="be-print-meta">
					${company ? esc(company) + "<br>" : ""}
					${__("Generated {0} by {1}", [esc(when), esc(who)])}
				</div>
			</div>
		`;
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
		// while filtering, show and open every group that holds a match, however
		// deep; a collapsed group hides its leaves, so count what the filter kept
		// rather than what is on screen
		this.$tree.find(".be-group").each(function () {
			const kept = $(this)
				.find(".be-leaf")
				.filter(function () {
					return this.style.display !== "none";
				}).length;
			$(this).toggle(!q || kept > 0);
			if (q && kept > 0) $(this).removeClass("be-collapsed");
		});
	}
};
