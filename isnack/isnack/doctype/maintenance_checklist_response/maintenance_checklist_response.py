from frappe.model.document import Document


class MaintenanceChecklistResponse(Document):
    def validate(self):
        self.flag_out_of_range()

    def flag_out_of_range(self):
        self.is_out_of_range = 0
        if self.input_type in ("Number", "Reading") and self.numeric_value is not None:
            if self.min_value and self.numeric_value < self.min_value:
                self.is_out_of_range = 1
            if self.max_value and self.numeric_value > self.max_value:
                self.is_out_of_range = 1
