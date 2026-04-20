function apply_po_receipt_row_mode(grid_row) {
    if (!grid_row || !grid_row.doc) return;
    const row = grid_row.doc;
    const batches = normalize_po_receipt_row_batches(row);
    const has_split = batches.length > 1;
    const $row = $(grid_row.row);

    if (has_split) {
      const totals = compute_po_receipt_batch_totals(batches);
      row.accepted_qty = totals.accepted;
      row.rejected_qty = totals.rejected;
      row.expiry_date = totals.min_expiry || null;
      row.batch_no = '';
    } else if (batches.length === 1) {
      row.accepted_qty = flt(batches[0].accepted_qty || 0);
      row.rejected_qty = flt(batches[0].rejected_qty || 0);
      row.batch_no = batches[0].batch_no || '';
      row.expiry_date = batches[0].expiry_date || null;
    } else {
      row.batch_no = '';
    }

    const readonly_fields = ['accepted_qty', 'rejected_qty', 'batch_no', 'expiry_date'];
    readonly_fields.forEach((fieldname) => {
      const $input = $row.find(`input[data-fieldname="${fieldname}"]`);
      if (!$input.length) return;
      $input.prop('readonly', has_split);
      if (fieldname === 'expiry_date') {
        $input.prop('disabled', has_split);
      }
      if (has_split) {
        $input.addClass('disabled');
      } else {
        $input.removeClass('disabled');
      }
    });

    const $accepted = $row.find('input[data-fieldname="accepted_qty"]');
    if ($accepted.length) $accepted.val(fmt_qty(row.accepted_qty || 0));
    const $rejected = $row.find('input[data-fieldname="rejected_qty"]');
    if ($rejected.length) $rejected.val(fmt_qty(row.rejected_qty || 0));
    const $batch = $row.find('input[data-fieldname="batch_no"]');
    if ($batch.length) $batch.val(has_split ? '' : (row.batch_no || ''));

    $row.find('[data-fieldname="batch_no"]').toggleClass('po-batch-split-active', has_split);
}