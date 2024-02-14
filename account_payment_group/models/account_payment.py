# © 2016 ADHOC SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime

import logging
_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    payment_group_id = fields.Many2one(
        'account.payment.group',
        'Payment Group',
        ondelete='cascade',
        readonly=True,
    )
    # we add this field so company can be send in context when adding payments
    # before payment group is saved
    payment_group_company_id = fields.Many2one(
        related='payment_group_id.company_id',
        string='Payment Group Company',
    )
    signed_amount = fields.Monetary(
        compute='_compute_signed_amount',
    )
    signed_amount_company_currency = fields.Monetary(
        string='Payment Amount on Company Currency',
        compute='_compute_signed_amount',
        currency_field='company_currency_id',
    )
    amount_company_currency = fields.Monetary(
        string='Amount on Company Currency',
        compute='_compute_amount_company_currency',
        inverse='_inverse_amount_company_currency',
        currency_field='company_currency_id',
    )
    other_currency = fields.Boolean(
        compute='_compute_other_currency',
    )
    force_amount_company_currency = fields.Monetary(
        string='Forced Amount on Company Currency',
        currency_field='company_currency_id',
        copy=False,
    )
    exchange_rate = fields.Float(
        string='Exchange Rate',
        compute='_compute_exchange_rate',
        # readonly=False,
        # inverse='_inverse_exchange_rate',
        digits=(16, 4),
    )
    company_currency_id = fields.Many2one(
        related='company_id.currency_id',
        string='Company currency',
    )
    company_id = fields.Many2one(related='move_id.company_id', string='Company',
                                 default=lambda self: self.env.company)

    l10n_ar_amount_company_currency_signed = fields.Monetary(
        currency_field='company_currency_id', compute='_compute_l10n_ar_amount_company_currency_signed')
    # campo a ser extendido y mostrar un nombre detemrinado en las lineas de
    # pago de un payment group o donde se desee (por ej. con cheque, retención,
    # etc)
    payment_method_description = fields.Char(
        compute='_compute_payment_method_description',
        string='Payment Method Desc.',
    )

    @api.depends('payment_method_id')
    def _compute_payment_method_description(self):
        for rec in self:
            rec.payment_method_description = rec.payment_method_id.display_name

    @api.depends('amount_company_currency', 'payment_type')
    def _compute_l10n_ar_amount_company_currency_signed(self):
        """ new field similar to amount_company_currency_signed but:
        1. is positive for payments to suppliers
        2. we use the new field amount_company_currency instead of amount_total_signed, because amount_total_signed is
        computed only after saving
        We use l10n_ar prefix because this is a pseudo backport of future l10n_ar_withholding module """
        for payment in self:
            if payment.payment_type == 'outbound' and payment.partner_type == 'customer' or \
                    payment.payment_type == 'inbound' and payment.partner_type == 'supplier':
                payment.l10n_ar_amount_company_currency_signed = -payment.amount_company_currency
            else:
                payment.l10n_ar_amount_company_currency_signed = payment.amount_company_currency

    def _get_valid_liquidity_accounts(self):
        return (
            self.journal_id.default_account_id,
            self.journal_id.payment_debit_account_id,
            self.journal_id.payment_credit_account_id,
        )

    def _seek_for_lines(self):

        ''' Helper used to dispatch the journal items between:
        - The lines using the temporary liquidity account.
        - The lines using the counterpart account.
        - The lines being the write-off lines.
        :return: (liquidity_lines, counterpart_lines, writeoff_lines)
        '''
        self.ensure_one()

        liquidity_lines = self.env['account.move.line']
        counterpart_lines = self.env['account.move.line']
        writeoff_lines = self.env['account.move.line']

        for line in self.move_id.line_ids:
            if line.account_id in self._get_valid_liquidity_accounts():
                if len(liquidity_lines) != 1:
                    liquidity_lines += line
            elif line.account_id.internal_type in ('receivable', 'payable') or line.partner_id == line.company_id.partner_id:
                if len(counterpart_lines) != 1:
                    counterpart_lines += line
            else:
                writeoff_lines += line

        return liquidity_lines, counterpart_lines, writeoff_lines

    def _synchronize_to_moves(self, changed_fields):
        ''' Update the account.move regarding the modified account.payment.
        :param changed_fields: A list containing all modified fields on account.payment.
        '''
        if self._context.get('skip_account_move_synchronization'):
            return

        if not any(field_name in changed_fields for field_name in (
            'date', 'amount', 'payment_type', 'partner_type', 'payment_reference', 'is_internal_transfer',
            'currency_id', 'partner_id', 'destination_account_id', 'partner_bank_id', 'journal_id',
        )):
            return

        for pay in self.with_context(skip_account_move_synchronization=True):
            if not pay.payment_group_id:
                liquidity_lines, counterpart_lines, writeoff_lines = pay._seek_for_lines()

                # Make sure to preserve the write-off amount.
                # This allows to create a new payment with custom 'line_ids'.

                if liquidity_lines and counterpart_lines and writeoff_lines:

                    counterpart_amount = sum(counterpart_lines.mapped('amount_currency'))
                    writeoff_amount = sum(writeoff_lines.mapped('amount_currency'))

                    # To be consistent with the payment_difference made in account.payment.register,
                    # 'writeoff_amount' needs to be signed regarding the 'amount' field before the write.
                    # Since the write is already done at this point, we need to base the computation on accounting values.
                    if (counterpart_amount > 0.0) == (writeoff_amount > 0.0):
                        sign = -1
                    else:
                        sign = 1
                    writeoff_amount = abs(writeoff_amount) * sign

                    write_off_line_vals = {
                        'name': writeoff_lines[0].name,
                        'amount': writeoff_amount,
                        'account_id': writeoff_lines[0].account_id.id,
                    }
                else:
                    write_off_line_vals = {}

                line_vals_list = pay._prepare_move_line_default_vals(write_off_line_vals=write_off_line_vals)

                line_ids_commands = []
                if liquidity_lines:
                    line_ids_commands.append((1, liquidity_lines.id, line_vals_list[0]))
                else:
                    line_ids_commands.append((0, 0, line_vals_list[0]))
                if counterpart_lines:
                    line_ids_commands.append((1, counterpart_lines.id, line_vals_list[1]))
                else:
                    line_ids_commands.append((0, 0, line_vals_list[1]))

                for line in writeoff_lines:
                    line_ids_commands.append((2, line.id))

                for extra_line_vals in line_vals_list[2:]:
                    line_ids_commands.append((0, 0, extra_line_vals))

                # Update the existing journal items.
                # If dealing with multiple write-off lines, they are dropped and a new one is generated.

                pay.move_id.write({
                    'partner_id': pay.partner_id.id,
                    'currency_id': pay.currency_id.id,
                    'partner_bank_id': pay.partner_bank_id.id,
                    'line_ids': line_ids_commands,
                })


    @api.depends(
        'amount', 'payment_type', 'partner_type', 'amount_company_currency')
    def _compute_signed_amount(self):
        for rec in self:
            sign = 1.0
            if (
                    (rec.partner_type == 'supplier' and
                        rec.payment_type == 'inbound') or
                    (rec.partner_type == 'customer' and
                        rec.payment_type == 'outbound')):
                sign = -1.0
            rec.signed_amount = rec.amount and rec.amount * sign
            rec.signed_amount_company_currency = (
                rec.amount_company_currency and
                rec.amount_company_currency * sign)

    @api.depends('currency_id')
    def _compute_other_currency(self):
        for rec in self:
            rec.other_currency = False
            if rec.company_currency_id and rec.currency_id and \
               rec.company_currency_id != rec.currency_id:
                rec.other_currency = True

    @api.onchange('payment_group_id')
    def onchange_payment_group_id(self):
        # now we change this according when use save & new the context from the payment was erased and we need to use some data.
        # this change is due this odoo change https://github.com/odoo/odoo/commit/c14b17c4855fd296fd804a45eab02b6d3566bb7a
        if self.payment_group_id:
            self.date = self.payment_group_id.payment_date
            self.partner_type = self.payment_group_id.partner_type
            self.partner_id = self.payment_group_id.partner_id
            self.payment_type = 'inbound' if self.payment_group_id.partner_type == 'customer' else 'outbound'
            if self.payment_group_id.payment_difference:
                self.amount = self.payment_group_id.payment_difference

    @api.depends('amount', 'other_currency', 'amount_company_currency')
    def _compute_exchange_rate(self):
        for rec in self:
            if rec.other_currency:
                rec.exchange_rate = rec.amount and (
                    rec.amount_company_currency / rec.amount) or 0.0
            else:
                rec.exchange_rate = False

    # this onchange is necesary because odoo, sometimes, re-compute
    # and overwrites amount_company_currency. That happends due to an issue
    # with rounding of amount field (amount field is not change but due to
    # rouding odoo believes amount has changed)
    @api.onchange('amount_company_currency')
    def _inverse_amount_company_currency(self):
        for rec in self:
            if rec.move_id.date:
                date = rec.move_id.date
            else:
                date = fields.Datetime.now()
            if rec.other_currency and rec.amount_company_currency != \
                    rec.currency_id._convert(
                        rec.amount, rec.company_id.currency_id,
                        rec.company_id, date):
                force_amount_company_currency = rec.amount_company_currency
            else:
                force_amount_company_currency = False
            rec.force_amount_company_currency = force_amount_company_currency

    @api.depends('amount', 'other_currency', 'force_amount_company_currency')
    def _compute_amount_company_currency(self):
        """
        * Si las monedas son iguales devuelve 1
        * si no, si hay force_amount_company_currency, devuelve ese valor
        * sino, devuelve el amount convertido a la moneda de la cia
        """
        for rec in self:
            if not rec.other_currency:
                amount_company_currency = rec.amount
            elif rec.force_amount_company_currency:
                amount_company_currency = rec.force_amount_company_currency
            else:
                if rec.move_id.date:
                    date = rec.move_id.date
                else:
                    date = fields.Datetime.now()
                amount_company_currency = rec.currency_id._convert(
                    rec.amount, rec.company_id.currency_id,
                    rec.company_id, date)
            rec.amount_company_currency = amount_company_currency

    def get_journals_domain(self):
        domain = super(AccountPayment, self).get_journals_domain()
        if self.payment_group_company_id:
            domain.append(
                ('company_id', '=', self.payment_group_company_id.id))
        return domain

    @api.constrains('payment_group_id', 'payment_type')
    def check_payment_group(self):
        # odoo tests don't create payments with payment gorups
        if self.env.registry.in_test_mode():
            return True
        counterpart_aml_dicts = self._context.get('counterpart_aml_dicts')
        counterpart_aml_dicts = counterpart_aml_dicts or [{}]
        for rec in self:
            receivable_payable = all([
                x.get('move_line') and x.get('move_line').account_id.internal_type in [
                    'receivable', 'payable'] for x in counterpart_aml_dicts])
            if rec.partner_type and rec.partner_id and receivable_payable and \
               not rec.payment_group_id:
                raise ValidationError(_(
                    'Payments with partners must be created from '
                    'payments groups'))
            # transfers or payments from bank reconciliation without partners
            elif not rec.partner_type and rec.payment_group_id:
                raise ValidationError(_(
                    "Payments without partners (usually transfers) cant't "
                    "have a related payment group"))

    @api.model
    def get_amls(self):
        """ Review parameters of process_reconciliation() method and transform
        them to amls recordset. this one is return to recompute the payment
        values
         context keys(
            'counterpart_aml_dicts', 'new_aml_dicts', 'payment_aml_rec')
         :return: account move line recorset
        """
        counterpart_aml_dicts = self._context.get('counterpart_aml_dicts')
        counterpart_aml_data = counterpart_aml_dicts or [{}]
        new_aml_data = self._context.get('new_aml_dicts', [])
        amls = self.env['account.move.line']
        if counterpart_aml_data:
            for item in counterpart_aml_data:
                amls |= item.get(
                    'move_line', self.env['account.move.line'])
        if new_aml_data:
            for aml_values in new_aml_data:
                amls |= amls.new(aml_values)
        return amls

    @api.model
    def infer_partner_info(self, vals):
        """ Odoo way to to interpret the partner_id, partner_type is not
        usefull for us because in some time they leave this ones empty and
        we need them in order to create the payment group.

        In this method will try to improve infer when it has a debt related
        taking into account the account type of the line to concile, and
        computing the partner if this ones is not setted when concile
        operation.

        return dictionary with keys (partner_id, partner_type)
        """
        res = {}
        # Get related amls
        amls = self.get_amls()
        if not amls:
            return res

        # odoo manda partner type segun si el pago es positivo o no, nosotros
        # mejoramos infiriendo a partir de que tipo de deuda se esta pagando
        partner_type = False
        internal_type = amls.mapped('account_id.internal_type')
        if len(internal_type) == 1:
            if internal_type == ['payable']:
                partner_type = 'supplier'
            elif internal_type == ['receivable']:
                partner_type = 'customer'
            if partner_type:
                res.update({'partner_type': partner_type})

        # por mas que el usuario no haya selecccionado partner, si esta pagando
        # deuda usamos el partner de esa deuda
        partner_id = vals.get('partner_id', False)
        if not partner_id and len(amls.mapped('partner_id')) == 1:
            partner_id = amls.mapped('partner_id').id
            res.update({'partner_id': partner_id})

        return res

    @api.model
    def create(self, vals):

        # Agregamos esta línea debido a que hay ocasiones donde primero cargan el pago y luego asignan el partner
        if 'payment_group_id' in vals:
            tmp_payment_group_id = self.env['account.payment.group'].search([('id','=',vals['payment_group_id'])])
            if tmp_payment_group_id:
                vals['partner_id'] = tmp_payment_group_id.partner_id.id

        """ When payments are created from bank reconciliation create the
        Payment group before creating payment to avoid raising error, only
        apply when the all the counterpart account are receivable/payable """
        aml_data = self._context.get('counterpart_aml_dicts') or self._context.get('new_aml_dicts') or [{}]
        if aml_data and not vals.get('partner_id'):
            vals.update(self.infer_partner_info(vals))

        receivable_payable_accounts = [
            (x.get('move_line') and x.get('move_line').account_id.internal_type in ['receivable', 'payable']) or
            (x.get('account_id') and self.env['account.account'].browse(x.get('account_id')).internal_type in [
                'receivable', 'payable'])
            for x in aml_data]
        create_from_statement = self._context.get('create_from_statement') and vals.get('partner_type') \
            and vals.get('partner_id') and all(receivable_payable_accounts)
        create_from_expense = self._context.get('create_from_expense', False)
        create_from_website = self._context.get('create_from_website', False)
        # NOTE: This is required at least from POS when we do not have
        # partner_id and we do not want a payment group in tha case.
        create_payment_group = \
            create_from_statement or create_from_website or create_from_expense
        _logger.info('creating payment group {}'.format(create_payment_group))
        if create_payment_group:
            company_id = self.env['account.journal'].browse(
                vals.get('journal_id')).company_id.id
            payment_group = self.env['account.payment.group'].create({
                'company_id': company_id,
                'partner_type': vals.get('partner_type'),
                'partner_id': vals.get('partner_id'),
                'payment_date': vals.get(
                    'payment_date', fields.Date.context_today(self)),
                'communication': vals.get('communication'),
            })
            vals['payment_group_id'] = payment_group.id
        payment = super(AccountPayment, self).create(vals)
        if create_payment_group:
            payment.payment_group_id.post()
        return payment

    @api.depends('journal_id', 'partner_id', 'partner_type', 'is_internal_transfer')
    def _compute_destination_account_id(self):
        """
        If we are paying a payment gorup with paylines, we use account
        of lines that are going to be paid
        """
        for rec in self:
            to_pay_account = rec.payment_group_id.to_pay_move_line_ids.mapped(
                'account_id')
            if len(to_pay_account) > 1:
                raise ValidationError(_(
                    'To Pay Lines must be of the same account!'))
            elif len(to_pay_account) == 1:
                rec.destination_account_id = to_pay_account[0]
            else:
                super(AccountPayment, rec)._compute_destination_account_id()

    def show_details(self):
        """
        Metodo para mostrar form editable de payment, principalmente para ser
        usado cuando hacemos ajustes y el payment group esta confirmado pero
        queremos editar una linea
        """
        return {
            'name': _('Payment Lines'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'account.payment',
            'target': 'new',
            'res_id': self.id,
            'context': self._context,
        }

    def _prepare_move_line_default_vals(self, write_off_line_vals=None):
        self.ensure_one()
        res = super(AccountPayment, self)._prepare_move_line_default_vals(write_off_line_vals)

        if self.force_amount_company_currency:
            difference = self.force_amount_company_currency - res[0]['credit'] - res[0]['debit']
            if res[0]['credit']:
                liquidity_field = 'credit'
                counterpart_field = 'debit'
            else:
                liquidity_field = 'debit'
                counterpart_field = 'credit'
            res[0].update({
                liquidity_field: self.force_amount_company_currency,
            })
            res[1].update({
                counterpart_field: res[1][counterpart_field] + difference,
            })
        return res

    def write(self, vals):
        super().write(vals)
        for rec in self:
            if rec.move_id.state == 'draft' and (rec.move_id._compute_name() == 'None' or rec.move_id._compute_name() != '/'):
                rec.move_id.name = '/'
                _logger.info("move_id name %s", rec.move_id.name)