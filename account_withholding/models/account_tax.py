from odoo import models, fields, api


class AccountTaxTemplate(models.Model):
    _inherit = "account.tax.template"

    type_tax_use = fields.Selection(
        selection_add=[
            ('customer', 'Customer Payment'),
            ('supplier', 'Supplier Payment'),
        ],
        ondelete={'customer': 'cascade', 'supplier': 'cascade'}
    )


class AccountTax(models.Model):
    """
    We could also use inherits but we should create methods of chart template
    """
    _inherit = "account.tax"

    type_tax_use = fields.Selection(
        selection_add=[
            ('customer', 'Customer Payment'),
            ('supplier', 'Supplier Payment'),
        ],
        ondelete={'customer': 'cascade', 'supplier': 'cascade'}
    )
    amount = fields.Float(
        default=0.0,
    )
    withholding_sequence_id = fields.Many2one(
        'ir.sequence',
        'Withholding Number Sequence',
        domain=[('code', '=', 'account.tax.withholding')],
        context=(
            "{'default_code': 'account.tax.withholding',"
            " 'default_name': name}"),
        help='If no sequence provided then it will be required for you to'
             ' enter withholding number when registering one.',
        # 'default_prefix': 'x-', 'default_padding': 8}",
        copy=False
    )

    @api.model
    def create(self, vals):
        tax = super(AccountTax, self).create(vals)
        if tax.type_tax_use == 'supplier' and not tax.withholding_sequence_id:
            tax.withholding_sequence_id = self.withholding_sequence_id.\
                sudo().create({
                    'name': tax.name,
                    'implementation': 'no_gap',
                    # 'prefix': False,
                    'padding': 8,
                    'number_increment': 1,
                    'code': 'account.tax.withholding',
                    'company_id': tax.company_id.id,
                }).id
        return tax
