from odoo import models, fields, api, _


class AccountPaymentGroup(models.Model):
    _inherit = "account.payment.group"

    @api.model_create_multi
    def create(self, vals_list):
        """Override the create method to add the context for use
        when the movelines is create."""
        self.env.context = dict(self.env.context)
        self.env.context.update({"difference_line": True})
        payments = super(AccountPaymentGroup, self).create(vals_list)
        return payments

    def write(self, vals):
        """Override the write method to add the context for use
        when the movelines is create."""
        self.env.context = dict(self.env.context)
        self.env.context.update({"difference_line": True})
        payments = super(AccountPaymentGroup, self).write(vals)
        return payments


class AccountPayment(models.Model):
    _inherit = "account.payment"

    difference_move_id = fields.Many2one(
        comodel_name="account.move",
        string="Difference Journal Entry",

        readonly=True,
        ondelete="cascade",
        check_company=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        payments = super(AccountPayment, self).create(vals_list)
        if self._context.get("difference_line", False):
            for pay in payments:
                if pay.force_amount_company_currency:
                    diff_amount = (
                        pay.force_amount_company_currency - pay.amount_total_signed
                    )
                    if diff_amount:
                        pay.generate_difference_move(diff_amount, pay.move_id)
        return payments

    def generate_difference_move(self, diff_amount, move):
        if diff_amount and len(self.line_ids) > 0:

            # get difference account
            company = self.move_id.company_id or self.company_id
            diff_account = (
                company.expense_currency_exchange_account_id
                if (diff_amount < 0)
                else company.income_currency_exchange_account_id
            )

            # create difference move
            diff_move_vals = self.get_diff_invoice_vals(move)
            self.difference_move_id = self.env["account.move"].create(diff_move_vals)

            # generate lines for difference move
            debit_line, credit_line = self.line_ids._get_diff_lines()

            self.balance_by_difference(debit_line, credit_line, diff_amount)

            self._generate_diff_amount_lines(
                debit_line,
                credit_line,
                diff_account,
                self.destination_account_id,
                diff_amount,
                self.difference_move_id,
            )

    def get_diff_invoice_vals(self, move):
        self.ensure_one()
        payment_group = self.payment_group_id
        if payment_group.partner_type == "supplier":
            invoice_type = "in_"
        else:
            invoice_type = "out_"

        if self._context.get("refund"):
            invoice_type += "refund"
        else:
            invoice_type += "invoice"

        return {
            "name": "Diferencia de cambio " + self.name,
            "date": self.date,
            "invoice_date": move.invoice_date,
            "invoice_origin": _("Payment id %s") % payment_group.id,
            "journal_id": self.journal_id.id,
            "invoice_user_id": move.user_id.id,
            "partner_id": move.partner_id.id,
            # 'type': move.type,
            "payment_id": move.payment_id.id,
        }

    def _generate_diff_amount_lines(
        self,
        debit_line,
        credit_line,
        diff_account,
        partner_acc_id,
        diff_amount,
        diff_move,
    ):
        rate = self._get_original_rate()[self.currency_id.id]
        company = self.move_id.company_id or self.company_id

        # debit
        diff_vals = {
            "move_id": diff_move.id,
            "partner_id": self.partner_id.id,
            "currency_id": self.currency_id.id,
            "name": debit_line.name,
            "date_maturity": debit_line.date_maturity,
            "amount_currency": 0,
            "debit": 0,
            "credit": 0,
            "account_id": diff_account.id,
        }
        # credit
        counterpart_vals = {
            "move_id": diff_move.id,
            "partner_id": self.partner_id.id,
            "currency_id": self.currency_id.id,
            "name": credit_line.name,
            "date_maturity": credit_line.date_maturity,
            "amount_currency": 0,
            "debit": 0,
            "credit": 0,
            "account_id": partner_acc_id.id,
        }

        if diff_amount < 0:  # diferencia a favor
            diff_vals["credit"] = abs(diff_amount)
            counterpart_vals["debit"] = abs(diff_amount)

        else:  # diferencia en contra
            diff_vals["debit"] = abs(diff_amount)
            counterpart_vals["credit"] = abs(diff_amount)

        lines_vals = [diff_vals, counterpart_vals]
        lines = (
            self.env["account.move.line"]
            .with_context(check_move_validity=False)
            .create(lines_vals)
        )

    def balance_by_difference(self, debit_line, credit_line, diff_amount):
        credit_line.with_context(check_move_validity=False).update(
            {"credit": abs(credit_line.credit) + (diff_amount)}
        )
        debit_line.with_context(check_move_validity=False).update(
            {"debit": abs(debit_line.debit) + (diff_amount)}
        )

    def _get_original_rate(self):
        return self.currency_id._get_rates(self.company_id, self.date)

    def _get_original_amount(self):
        return self.currency_id._convert(
            self.amount, self.company_id.currency_id, self.company_id, self.date
        )
