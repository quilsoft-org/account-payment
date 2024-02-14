from odoo import fields, models, _


class AccountCheckPaymentActionWizard(models.TransientModel):
    _name = 'account.check.payment.action.wizard'
    _description = 'Payment validate Wizard'

    def action_validate(self):
        payment = self.env['account.payment.group'].browse(self._context.get('active_ids'))
        payment.is_valid = True


