# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
import math
from frappe.model.document import Document


class QCWeightCheck(Document):
    def validate(self):
        samples = self.samples or []
        tu1 = self.tu1_limit or 0
        tu2 = self.tu2_limit or 0

        for s in samples:
            s.net_weight = (s.gross_weight or 0) - (s.tare_weight or 0)
            s.in_range = 1 if s.net_weight >= tu2 else 0

        net_weights = [s.net_weight for s in samples if s.net_weight is not None]
        self.sample_count = len(net_weights)
        if net_weights:
            self.average_weight = sum(net_weights) / len(net_weights)
            mean = self.average_weight
            variance = sum((w - mean) ** 2 for w in net_weights) / len(net_weights)
            self.std_deviation = math.sqrt(variance)
            self.min_weight = min(net_weights)
            self.max_weight = max(net_weights)
            self.tu1_failures = sum(1 for w in net_weights if w < tu1)
            self.tu2_failures = sum(1 for w in net_weights if w < tu2)
        else:
            self.average_weight = 0
            self.std_deviation = 0
            self.min_weight = 0
            self.max_weight = 0
            self.tu1_failures = 0
            self.tu2_failures = 0
