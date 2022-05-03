from odoo import models, fields, api


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.model_create_multi
    def create(self, vals_list):
        """Override the create method to add the is_duplicate_line method."""
        lines = super(AccountMoveLine, self).create(vals_list)
        return lines

    def _get_diff_lines(self):
        diff_line = None
        credit_line = None
        for l in self:
            if not diff_line and l.debit > 0:
                diff_line = l
            if not credit_line and l.credit > 0:
                credit_line = l
            if credit_line and diff_line:
                break
        return diff_line, credit_line
