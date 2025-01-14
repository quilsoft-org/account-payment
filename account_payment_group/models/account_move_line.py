# © 2016 ADHOC SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, api
# from odoo.exceptions import UserError, ValidationError


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    # inverse field of the one created on payment groups, used by other modules
    # like sipreco
    payment_group_ids = fields.Many2many(
        'account.payment.group',
        'account_move_line_payment_group_to_pay_rel',
        'to_pay_line_id',
        'payment_group_id',
        string="Payment Groups",
        readonly=True,
        copy=False,
        # auto_join not yet implemented for m2m. TODO enable when implemented
        # https://github.com/odoo/odoo/blob/master/odoo/osv/expression.py#L899
        # auto_join=True,
    )

    @api.depends_context('payment_group_id')
    def _compute_payment_group_matched_amount(self):
        """
        Reciviendo un payment_group_id por contexto, decimos en ese payment
        group, cuanto se pago para la lína en cuestión.
        """
        payment_group_id = self._context.get('payment_group_id')
        if not payment_group_id:
            self.payment_group_matched_amount = 0.0
            return False
        payments = self.env['account.payment.group'].browse(
            payment_group_id).payment_ids
        payment_move_lines = payments.mapped('line_ids')

        for rec in self:
            matched_amount = 0.0
            reconciles = self.env['account.partial.reconcile'].search([
                ('credit_move_id', 'in', payment_move_lines.ids),
                ('debit_move_id', '=', rec.id)])
            matched_amount += sum(reconciles.mapped('amount'))

            reconciles = self.env['account.partial.reconcile'].search([
                ('debit_move_id', 'in', payment_move_lines.ids),
                ('credit_move_id', '=', rec.id)])
            matched_amount -= sum(reconciles.mapped('amount'))
            rec.payment_group_matched_amount = matched_amount

    payment_group_matched_amount = fields.Monetary(
        compute='_compute_payment_group_matched_amount',
        currency_field='company_currency_id',
    )


    def create(self, vals_list):
        if vals_list and 'move_id' in vals_list:
            move_id = vals_list.get('move_id', False)
            if move_id:
                move = self.env['account.move'].search([('id','=', move_id)])
                if move.payment_id and move.payment_id.force_amount_company_currency:
                    if vals_list['debit']:
                        vals_list['debit'] = move.payment_id.force_amount_company_currency
                    if vals_list['credit']:
                        vals_list['credit'] = move.payment_id.force_amount_company_currency
        return super(AccountMoveLine, self).create(vals_list)
