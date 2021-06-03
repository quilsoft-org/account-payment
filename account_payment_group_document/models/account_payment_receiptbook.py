##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)


class AccountPaymentReceiptbook(models.Model):

    _name = 'account.payment.receiptbook'
    _description = 'Account payment Receiptbook'
    # analogo a account.journal.document.type pero para pagos
    _order = 'sequence asc'

    report_partner_id = fields.Many2one(
        'res.partner',
    )
    mail_template_id = fields.Many2one(
        'mail.template',
        'Email Template',
        domain=[('model', '=', 'account.payment.group')],
        help="If set an email will be sent to the customer when the related"
        " account.payment.group has been posted.",
    )

    sequence = fields.Integer(
        'Sequence',
        help="Used to order the receiptbooks",
        default=10,
    )
    name = fields.Char(
        'Name',
        size=64,
        required=True,
        index=True,
    )
    partner_type = fields.Selection(
        [('customer', 'Customer'), ('supplier', 'Vendor')],
        required=True,
        index=True,
    )
    first_number = fields.Integer(
        string='First Number',
        default=1,
        required=True
    )
    next_number = fields.Integer(
        related='sequence_id.number_next_actual',
        readonly=False,
    )

    # Evaluer crear secuencias manuales
    # Lo dejo por eso
    sequence_type = fields.Selection(
        [('automatic', 'Automatic'), ('manual', 'Manual')],
        string='Sequence Type',
        readonly=False,
        default='automatic',
    )
    sequence_id = fields.Many2one(
        'ir.sequence',
        'Entry Sequence',
        help="This field contains the information related to the numbering "
        "of the receipt entries of this receiptbook.",
        copy=False,
    )
    company_id = fields.Many2one(
        'res.company',
        'Company',
        required=True,
        default=lambda self: self.env[
            'res.company']._company_default_get('account.payment.receiptbook')
    )
    prefix = fields.Char(
        'Prefix',
        # required=True,
        # TODO rename field to prefix
    )
    padding = fields.Integer(
        'Number Padding',
        default=8,
        help="automatically adds some '0' on the left of the 'Number' to get "
        "the required padding size."
    )
    active = fields.Boolean(
        'Active',
        default=True,
    )
    l10n_latam_document_type_id = fields.Many2one(
        'l10n_latam.document.type',
        'Document Type',
        required=True,
    )
