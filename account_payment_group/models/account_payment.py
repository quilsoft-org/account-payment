# © 2016 ADHOC SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError,UserError

import logging
_logger = logging.getLogger(__name__)


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'
    payment_group_id = fields.Many2one(
        'account.payment.group',
        'Payment Group',
        readonly=True,
    )
    payment_group_company_id = fields.Many2one(
        related='payment_group_id.company_id',
        string='Payment Group Company',
    )
    payment_type_copy = fields.Selection(
        selection=[('outbound', 'Send Money'), ('inbound', 'Receive Money')],
        compute='_compute_payment_type_copy',
        inverse='_inverse_payment_type_copy',
        string='Payment Type (without transfer)'
    )

    @api.onchange('payment_type_copy')
    def _inverse_payment_type_copy(self):
        for rec in self:
            # if false, then it is a transfer
            rec.payment_type = (
                rec.payment_type_copy and rec.payment_type_copy or 'transfer')

    @api.depends('payment_type')
    def _compute_payment_type_copy(self):
        for rec in self:
            if rec.payment_type == 'transfer':
                rec.payment_type_copy = False
            else:
                rec.payment_type_copy = rec.payment_type

    def _create_payment_vals_from_wizard(self):
        payment_vals = super()._create_payment_vals_from_wizard()
        payment_vals['payment_group_id'] = self.payment_group_id.id
        payment_vals['payment_group_company_id'] = self.payment_group_company_id.id
        payment_vals['payment_type_copy'] = self.payment_type_copy

        return payment_vals

    #@api.onchange('payment_type')
    #def _onchange_payment_type(self):
    #    """
    #    we disable change of partner_type if we came from a payment_group
    #    but we still reset the journal
    #    """
    #    if not self._context.get('payment_group'):
    #        return super(AccountPayment, self)._onchange_payment_type()
    #    self.journal_id = False


class AccountPayment(models.Model):
    _inherit = "account.payment"

    partner_bank_id = fields.Many2one(
        comodel_name='res.partner.bank',
        string="Recipient Bank Account",
        readonly=False,
        store=True,
        compute='_compute_partner_bank_id',
    )


    destination_journal_id = fields.Many2one('account.journal', string='Transferir a',
                                             domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")

    partner_type = fields.Selection(required=False)
    payment_type = fields.Selection(selection_add=[('transfer','Transferencia')], ondelete={'transfer': 'set default'},required=False)


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
    # we make a copy without transfer option, we try with related but it
    # does not works
    payment_type_copy = fields.Selection(
        selection=[('outbound', 'Send Money'), ('inbound', 'Receive Money')],
        compute='_compute_payment_type_copy',
        inverse='_inverse_payment_type_copy',
        string='Payment Type (without transfer)'
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
    communication = fields.Char(
        string='Memo',
        readonly=True,
        states={'draft': [('readonly', False)]},
    )
    paired_internal_transfer_payment_id = fields.Many2one('account.payment',
                                                          help="When an internal transfer is posted, a paired payment is created. "
                                                               "They are cross referenced trough this field",
                                                          copy=False)


    transfer_with_brige_accounts = fields.Boolean(string="Usar cuenta puente de transferencia",default=False,
                                                  help="If this field is  true, each transfer will have two account.move with account bridge")
        
    def _synchronize_to_moves(self, changed_fields):
        payment_other_currency = self.filtered(lambda payment: payment.other_currency)
        payment_company_currency = self - payment_other_currency
        #if self.move_id.line_ids and 'skip_account_move_synchronization' not in self._context:
        #    self.move_id.line_ids = False

        for payment in payment_other_currency: 
            super(AccountPayment, payment.with_context(force_rate_to=payment.exchange_rate))._synchronize_to_moves(changed_fields)
        super(AccountPayment, payment_company_currency)._synchronize_to_moves(changed_fields)


    def action_post(self):
        res = super(AccountPayment, self).action_post()
        for rec in self:
            if rec.transfer_with_brige_accounts:
                rec.filtered(
                    lambda pay: pay.payment_type  == 'transfer' and not pay.paired_internal_transfer_payment_id
                )._create_paired_internal_transfer_payment()

        return res

    def _create_paired_internal_transfer_payment(self):
        ''' When an internal transfer is posted, a paired payment is created
        with opposite payment_type and swapped journal_id & destination_journal_id.
        Both payments liquidity transfer lines are then reconciled.
        '''
        for payment in self:

            paired_payment = payment.copy({
                'journal_id': payment.destination_journal_id.id,
                'destination_journal_id': payment.journal_id.id,
                'payment_type': 'transfer',
                'move_id': None,
                'ref': payment.ref,
                'paired_internal_transfer_payment_id': payment.id,
                'date': payment.date,
            })

            payment.paired_internal_transfer_payment_id = paired_payment
            paired_payment.move_id._post(soft=False)


            body = _('This payment has been created from <a href=# data-oe-model=account.payment data-oe-id=%d>%s</a>') % (payment.id, payment.name)
            paired_payment.message_post(body=body)
            body = _('A second payment has been created: <a href=# data-oe-model=account.payment data-oe-id=%d>%s</a>') % (paired_payment.id, paired_payment.name)
            payment.message_post(body=body)

            lines = (payment.move_id.line_ids + paired_payment.move_id.line_ids).filtered(
                lambda l: l.account_id == payment.destination_account_id and not l.reconciled)
            lines.reconcile()

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

    # TODO check why we get error with depend on company_id and fix it
    # (recursive dependency?). The error is on paymentrs tree/form view
    # @api.depends('currency_id', 'company_id')
    @api.depends('currency_id')
    def _compute_other_currency(self):
        for rec in self:
            rec.other_currency = False
            if rec.company_currency_id and rec.currency_id and \
               rec.company_currency_id != rec.currency_id:
                rec.other_currency = True

    @api.onchange('payment_group_id')
    def onchange_payment_group_id(self):
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
        for rec in self.with_context():
            self.move_id.line_ids.unlink()
            if rec.other_currency and rec.amount_company_currency != \
                    rec.currency_id._convert(
                        rec.amount, rec.company_id.currency_id,
                        rec.company_id, rec.date):
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
        for rec in self.with_context(skip_account_move_synchronization=True):
            if not rec.other_currency:
                amount_company_currency = rec.amount
            elif rec.force_amount_company_currency:
                amount_company_currency = rec.force_amount_company_currency
            else:
                amount_company_currency = rec.currency_id._convert(
                    rec.amount, rec.company_id.currency_id,
                    rec.company_id, rec.date)
            rec.amount_company_currency = amount_company_currency

    @api.onchange('payment_type_copy')
    def _inverse_payment_type_copy(self):
        for rec in self.with_context(skip_account_move_synchronization=True):
            # if false, then it is a transfer
            rec.payment_type = (
                rec.payment_type_copy and rec.payment_type_copy or 'transfer')


    @api.depends('payment_type')
    def _compute_payment_type_copy(self):
        for rec in self.with_context(skip_account_move_synchronization=True):
            if rec.payment_type == 'transfer':
                rec.payment_type_copy = False
            else:
                rec.payment_type_copy = rec.payment_type

    def get_journals_domain(self):
        domain = super(AccountPayment, self).get_journals_domain()
        if self.payment_group_company_id:
            domain.append(
                ('company_id', '=', self.payment_group_company_id.id))
        return domain

    @api.onchange('journal_id')
    def _onchange_journal_id(self):
        self.name = '/'


    @api.onchange('payment_type')
    def _onchange_payment_type(self):
        """
        we disable change of partner_type if we came from a payment_group
        but we still reset the journal
        """
        if not self._context.get('payment_group'):
            return super(AccountPayment, self)._onchange_payment_type()
        self.journal_id = False

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

    @api.model_create_multi
    def create(self, vals_list):
        """ When payments are created from bank reconciliation create the
        Payment group before creating payment to avoid raising error, only
        apply when the all the counterpart account are receivable/payable """
        for vals in vals_list:

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
            if create_payment_group:
                company_id = self.env['account.journal'].browse(
                    vals.get('journal_id')).company_id.id
                if not company_id:
                    payment_transaction = self.env['payment.transaction'].search([('id','=',vals.get('payment_transaction_id'))])
                    if payment_transaction:
                        company_id = payment_transaction.acquirer_id.company_id.id
                payment_group = self.env['account.payment.group'].create({
                    'company_id': company_id,
                    'partner_type': vals.get('partner_type'),
                    'partner_id': vals.get('partner_id'),
                    'payment_date': vals.get(
                        'date', fields.Date.context_today(self)),
                    'communication': vals.get('communication'),
                })
                vals_list[0]['payment_group_id'] = payment_group.id

        payment = super().create(vals_list)
        if create_payment_group:
            payment.payment_group_id.post()
        return payment

    @api.depends('available_partner_bank_ids', 'journal_id','destination_journal_id')
    def _compute_partner_bank_id(self):
        ''' The default partner_bank_id will be the first available on the partner. '''
        for pay in self:
            if pay.payment_type == 'transfer' and pay.destination_journal_id:
                pay.partner_bank_id = pay.destination_journal_id.bank_account_id.id
            else:
                return super(AccountPayment, self)._compute_partner_bank_id()
    @api.depends('journal_id', 'partner_id', 'partner_type', 'is_internal_transfer')
    def _compute_destination_account_id(self):
        """
        If we are paying a payment gorup with paylines, we use account
        of lines that are going to be paid
        """
        pired_payment = self.search([('paired_internal_transfer_payment_id','=',self.id)])
        if self.payment_type == 'transfer':
            self.destination_account_id = self.journal_id.company_id.transfer_account_id
        else:
            for rec in self.with_context(skip_account_move_synchronization=True):
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
        ''' Prepare the dictionary to create the default account.move.lines for the current payment.
        :param write_off_line_vals: Optional dictionary to create a write-off account.move.line easily containing:
            * amount:       The amount to be added to the counterpart amount.
            * name:         The label to set on the line.
            * account_id:   The account on which create the write-off.
        :return: A list of python dictionary to be passed to the account.move.line's 'create' method.
        '''
        if self.payment_type  == 'transfer':
            self.ensure_one()
            write_off_line_vals = write_off_line_vals or {}

            if not self.journal_id.payment_debit_account_id or not self.journal_id.payment_credit_account_id:
                raise UserError(_(
                    "You can't create a new payment without an outstanding payments/receipts account set on the %s journal.",
                    self.journal_id.display_name))

            # Compute amounts.
            write_off_amount_currency = write_off_line_vals.get('amount', 0.0)

            if self.payment_type == 'inbound':
                # Receive money.
                liquidity_amount_currency = self.amount
            elif self.payment_type == 'outbound':
                # Send money.
                liquidity_amount_currency = -self.amount
                write_off_amount_currency *= -1
            elif self.payment_type == 'transfer':
                liquidity_amount_currency = self.amount
            else:
                liquidity_amount_currency = write_off_amount_currency = 0.0

            write_off_balance = self.currency_id._convert(
                write_off_amount_currency,
                self.company_id.currency_id,
                self.company_id,
                self.date,
            )
            liquidity_balance = self.currency_id._convert(
                liquidity_amount_currency,
                self.company_id.currency_id,
                self.company_id,
                self.date,
            )
            counterpart_amount_currency = -liquidity_amount_currency - write_off_amount_currency
            counterpart_balance = -liquidity_balance - write_off_balance
            currency_id = self.currency_id.id

            if self.is_internal_transfer:
                if self.payment_type == 'inbound':
                    liquidity_line_name = _('Transfer to %s', self.journal_id.name)
                else: # payment.payment_type == 'outbound':
                    liquidity_line_name = _('Transfer from %s', self.journal_id.name)
            else:
                liquidity_line_name = self.payment_reference

            # Compute a default label to set on the journal items.

            payment_display_name =  {
                'outbound-customer': _("Customer Reimbursement"),
                'inbound-customer': _("Customer Payment"),
                'outbound-supplier': _("Vendor Payment"),
                'inbound-supplier': _("Vendor Reimbursement"),
                'transfer': 'Transferencia'
            }

            default_line_name = self.env['account.move.line']._get_default_line_name(
                _("Internal Transfer") if self.is_internal_transfer else payment_display_name['%s' % (self.payment_type)],
                self.amount,
                self.currency_id,
                self.date,
                partner=self.partner_id,
            )
            is_company_currency = self.company_id.currency_id.id == currency_id
            if self.transfer_with_brige_accounts:
                line_vals_list = [
                    # Liquidity line.
                    {
                        'name': liquidity_line_name or default_line_name,
                        'date_maturity': self.date,
                        'amount_currency': liquidity_amount_currency,
                        'currency_id': currency_id,
                        'debit':-liquidity_balance if liquidity_balance < 0.0 else 0.0,
                        'credit': liquidity_balance if liquidity_balance > 0.0 else 0.0,
                        'partner_id': self.partner_id.id,
                        'account_id': (self.company_id.transfer_account_id.id )if self.paired_internal_transfer_payment_id else self.journal_id.payment_debit_account_id.id
                                                if not self.paired_internal_transfer_payment_id else self.company_id.transfer_account_id.id,
                    },
                    # Receivable / Payable.
                    {
                        'name': self.payment_reference or default_line_name,
                        'date_maturity': self.date,
                        'amount_currency': counterpart_amount_currency,
                        'currency_id': currency_id,
                        'debit':  -counterpart_balance if counterpart_balance < 0.0 else 0.0,
                        'credit':counterpart_balance if counterpart_balance > 0.0 else 0.0,
                        'partner_id': self.partner_id.id,
                        'account_id': (self.company_id.transfer_account_id.id)
                        if not self.paired_internal_transfer_payment_id else self.journal_id.payment_debit_account_id.id
                    },
                ]
            else:
                line_vals_list = [
                    # Liquidity line.
                    {
                        'name': liquidity_line_name or default_line_name,
                        'date_maturity': self.date,
                        'amount_currency': liquidity_amount_currency *(-1 if not is_company_currency else 1),
                        'currency_id': currency_id,
                        'debit': -liquidity_balance if liquidity_balance < 0.0 else 0.0,
                        'credit': liquidity_balance if liquidity_balance > 0.0 else 0.0,
                        'partner_id': self.partner_id.id,
                        'account_id': self.journal_id.payment_credit_account_id.id if liquidity_balance < 0.0 else self.journal_id.payment_debit_account_id.id,
                    },
                    # Receivable / Payable.
                    {
                        'name': self.payment_reference or default_line_name,
                        'date_maturity': self.date,
                        'amount_currency': counterpart_amount_currency *(-1 if not is_company_currency else 1),
                        'currency_id': currency_id,
                        'debit': -counterpart_balance if counterpart_balance < 0.0 else 0.0,
                        'credit': counterpart_balance if counterpart_balance > 0.0 else 0.0,
                        'partner_id': self.partner_id.id,
                        'account_id': self.destination_journal_id.payment_credit_account_id.id if liquidity_balance < 0.0 else self.destination_journal_id.payment_debit_account_id.id,
                    },
                ]
            if not self.currency_id.is_zero(write_off_amount_currency):
                # Write-off line.
                line_vals_list.append({
                    'name': write_off_line_vals.get('name') or default_line_name,
                    'amount_currency': write_off_amount_currency,
                    'currency_id': currency_id,
                    'debit': -write_off_balance if write_off_balance < 0.0 else 0.0,
                    'credit': write_off_balance if write_off_balance > 0.0 else 0.0,
                    'partner_id': self.partner_id.id,
                    'account_id': write_off_line_vals.get('account_id'),
                })
            return line_vals_list
        else:
            return super(AccountPayment, self)._prepare_move_line_default_vals(write_off_line_vals=write_off_line_vals)


    def _synchronize_from_moves(self, changed_fields):
        if  self and self[0].payment_type  != 'transfer':
           super(AccountPayment, self)._synchronize_from_moves(changed_fields)
        elif not self and changed_fields:
            super(AccountPayment, self)._synchronize_from_moves(changed_fields)


    def _prepare_payment_moves(self):
        all_moves_vals = []
        for rec in self:
            moves_vals = super(AccountPayment, rec)._prepare_payment_moves()
            for move_vals in moves_vals:
                # If we have a communication on payment group append it before payment communication
                if rec.payment_group_id.communication:
                    move_vals['ref'] = "%s%s" % (self.payment_group_id.communication, move_vals['ref'] or '')

                # Si se esta forzando importe en moneda de cia, usamos este importe para debito/credito
                if rec.force_amount_company_currency:
                    for line in move_vals['line_ids']:
                        if line[2].get('debit'):
                            line[2]['debit'] = rec.force_amount_company_currency
                        if line[2].get('credit'):
                            line[2]['credit'] = rec.force_amount_company_currency
                all_moves_vals += [move_vals]
        return all_moves_vals
