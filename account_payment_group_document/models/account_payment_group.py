##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)


class AccountPaymentGroup(models.Model):
    _name = "account.payment.group"
    _inherit = ['account.payment.group', 'sequence.mixin']
  
    _order = "payment_date desc, name desc, id desc"
    _check_company_auto = True
    _sequence_index = "receiptbook_id"
    _sequence_date_field = 'payment_date'

    document_sequence_id = fields.Many2one(
        related='receiptbook_id.sequence_id',
    )
    receiptbook_id = fields.Many2one(
        'account.payment.receiptbook',
        'ReceiptBook',
        readonly=True,
        states={'draft': [('readonly', False)]},
        auto_join=True,
        check_company=True,
    )
    document_type_id = fields.Many2one(
        related='receiptbook_id.l10n_latam_document_type_id',
    )
    next_number = fields.Integer(
        # related='receiptbook_id.sequence_id.number_next_actual',
        compute='_compute_next_number',
        string='Next Number',
    )
    # this field should be created on account_payment_document so that we have
    # a name if we don't work with account.document.type
    name = fields.Char(
        string='Document Reference',
        copy=False,
        #default='/'
    )
    l10n_latam_document_number = fields.Char(
        compute='_compute_l10n_latam_document_number', inverse='_inverse_l10n_latam_document_number',
        string='Document Number', readonly=True, states={'draft': [('readonly', False)]})

    _sql_constraints = [
        ('name_uniq', 'unique(name, receiptbook_id)',
            'Document number must be unique per receiptbook!')]

    def _get_starting_sequence(self):
        if self.document_type_id:
            #return 0
            return "%s 00000000" % (self.document_type_id.doc_code_prefix)
        # There was no pattern found, propose one
        return ""

    def _get_last_sequence_domain(self, relaxed=False):
        self.ensure_one()
        if not self.receiptbook_id:
            return "WHERE FALSE", {}
        where_string = "WHERE receiptbook_id = %(receiptbook_id)s AND (name != '/' or name is not NULL)"
        param = {'receiptbook_id': self.receiptbook_id.id}

        return where_string, param

    @api.model
    def _deduce_sequence_number_reset(self, name):
        return 'never'

    @api.depends('name')
    def _compute_l10n_latam_document_number(self):
        recs_with_name = self.filtered('name')
        for rec in recs_with_name:
            name = rec.name
            doc_code_prefix = rec.document_type_id.doc_code_prefix
            if doc_code_prefix and name:
                name = name.split(" ", 1)[-1]
            rec.l10n_latam_document_number = name
        remaining = self - recs_with_name
        remaining.l10n_latam_document_number = False

    @api.onchange('document_type_id', 'l10n_latam_document_number')
    def _inverse_l10n_latam_document_number(self):
        for rec in self.filtered('document_type_id'):
            if not rec.l10n_latam_document_number:
                rec.name = False
            else:
                document_number = rec.document_type_id._format_document_number(rec.l10n_latam_document_number)
                if rec.l10n_latam_document_number != document_number:
                    rec.l10n_latam_document_number = document_number
                rec.name = "%s %s" % (rec.document_type_id.doc_code_prefix, document_number)

    @api.depends(
        'receiptbook_id.sequence_id.number_next_actual',
    )
    def _compute_next_number(self):
        """
        show next number only for payments without number and on draft state
        """

        self.ensure_one()
        if 'draft' in self.mapped('state'): 
            last_sequence = self._get_last_sequence()
            new = not last_sequence
            if new:
                last_sequence = self._get_last_sequence(relaxed=True) or self._get_starting_sequence()

            format, format_values = self._get_sequence_format_param(last_sequence)
            if new:
                format_values['seq'] = 0
                format_values['year'] = self[self._sequence_date_field].year % (10 ** format_values['year_length'])
                format_values['month'] = self[self._sequence_date_field].month
        i = 0
        for payment in self:
            if payment.state != 'draft' or not payment.receiptbook_id or payment.l10n_latam_document_number:
                payment.next_number = False
                continue
            i += 1
            payment.next_number = format_values['seq'] + i

    @api.constrains('company_id', 'partner_type')
    def _force_receiptbook(self):
        # we add cosntrins to fix odoo tests and also help in inmpo of data
        for rec in self:
            if not rec.receiptbook_id:
                rec.receiptbook_id = rec._get_receiptbook()

    @api.onchange('company_id', 'partner_type')
    def get_receiptbook(self):
        self.receiptbook_id = self._get_receiptbook()

    def _get_receiptbook(self):
        self.ensure_one()
        partner_type = self.partner_type or self._context.get(
            'partner_type', self._context.get('default_partner_type', False))
        receiptbook = self.env[
            'account.payment.receiptbook'].search([
                ('partner_type', '=', partner_type),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
        return receiptbook

    def post(self):
        for rec in self:
            _logger.info(rec.name)
            if not rec.name or rec.name == '/':
                rec._set_next_sequence()

                #if rec.receiptbook_id.sequence_id:
                #    rec.l10n_latam_document_number = (
                #        rec.receiptbook_id.with_context(
                #            ir_sequence_date=rec.payment_date
                #        ).sequence_id.next_by_id())
            # rec.payment_ids.move_name = rec.name

            # hacemos el llamado acá y no arriba para primero hacer los checks
            # y ademas primero limpiar o copiar talonario antes de postear.
            # lo hacemos antes de mandar email asi sale correctamente numerado
            # necesitamos realmente mandar el tipo de documento? lo necesitamos para algo?
            super(AccountPaymentGroup, self.with_context(
                default_l10n_latam_document_type_id=rec.document_type_id.id)).post()
            if not rec.receiptbook_id:
                rec.name = any(
                    rec.payment_ids.mapped('name')) and ', '.join(
                    rec.payment_ids.mapped('name')) or False

        for rec in self:
            if rec.receiptbook_id.mail_template_id:
                rec.message_post_with_template(
                    rec.receiptbook_id.mail_template_id.id,
                )
        return True
