##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = "account.payment"

    tax_withholding_id = fields.Many2one(
        'account.tax',
        string='Withholding Tax',
        readonly=True,
        states={'draft': [('readonly', False)]},
    )
    withholding_number = fields.Char(
        readonly=True,
        states={'draft': [('readonly', False)]},
        help="If you don't set a number we will add a number automatically "
        "from a sequence that should be configured on the Withholding Tax"
    )
    withholding_base_amount = fields.Monetary(
        string='Withholding Base Amount',
        readonly=True,
        states={'draft': [('readonly', False)]},
    )

    def action_post(self):
        without_number = self.filtered(
            lambda x: x.tax_withholding_id and not x.withholding_number)

        without_sequence = without_number.filtered(
            lambda x: not x.tax_withholding_id.withholding_sequence_id)
        if without_sequence:
            raise UserError(_(
                'No puede validar pagos con retenciones que no tengan número '
                'de retención. Recomendamos agregar una secuencia a los '
                'impuestos de retención correspondientes. Id de pagos: %s') % (
                without_sequence.ids))

        # a los que tienen secuencia les setamos el numero desde secuencia
        for payment in (without_number - without_sequence):
            payment.withholding_number = \
                payment.tax_withholding_id.withholding_sequence_id.next_by_id()

        return super(AccountPayment, self).action_post()

    def _prepare_move_line_default_vals(self, write_off_line_vals=None):

        line_vals_list = super()._prepare_move_line_default_vals(write_off_line_vals)

        if self.payment_method_code == 'withholding':
            if self.payment_type == 'transfer':
                raise UserError(_(
                    'You can not use withholdings on transfers!'))
            if (
                    (self.partner_type == 'customer' and
                        self.payment_type == 'inbound') or
                    (self.partner_type == 'supplier' and
                        self.payment_type == 'outbound')):
                rep_field = 'invoice_repartition_line_ids'
            else:
                rep_field = 'refund_repartition_line_ids'
            rep_lines = self.tax_withholding_id[rep_field].filtered(lambda x: x.repartition_type == 'tax')
            if len(rep_lines) != 1:
                raise UserError(
                    'En los impuestos de retención debe haber una línea de repartición de tipo tax para pagos y otra'
                    'para reembolsos')

            account = rep_lines.account_id
            line_vals_list[0]['account_id'] = account.id
            line_vals_list[0]['tax_repartition_line_id'] = rep_lines.id


        return line_vals_list




    @api.depends('payment_method_code', 'tax_withholding_id.name')
    def _compute_payment_method_description(self):
        payments = self.filtered(
            lambda x: x.payment_method_code == 'withholding')
        for rec in payments:
            name = rec.tax_withholding_id.name or rec.payment_method_id.name
            rec.payment_method_description = name
        return super(
            AccountPayment,
            (self - payments))._compute_payment_method_description()

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------
    # agrego a esta funcion la cuenta deferred
    # no es una solucion elegante pero necesito usar
    # esta cuenta como si fuera liquida solo algunas veces
    def _seek_for_lines_liquidity_accounts(self):
        accounts = super()._seek_for_lines_liquidity_accounts()

        if self.payment_method_code == 'withholding':
            if (
                    (self.partner_type == 'customer' and
                        self.payment_type == 'inbound') or
                    (self.partner_type == 'supplier' and
                        self.payment_type == 'outbound')):
                rep_field = 'invoice_repartition_line_ids'
            else:
                rep_field = 'refund_repartition_line_ids'

            rep_lines = self.tax_withholding_id[rep_field].filtered(lambda x: x.repartition_type == 'tax')
            accounts.append(rep_lines.account_id)

        return accounts
