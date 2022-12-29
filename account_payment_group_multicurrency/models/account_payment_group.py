# -*- coding: utf-8 -*-

from os import unlink
from odoo import models, api, fields, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class AccountPaymentGroup(models.Model):
    _inherit = "account.payment.group"


    def post(self):
        create_from_website = self._context.get("create_from_website", False)
        create_from_statement = self._context.get("create_from_statement", False)
        create_from_expense = self._context.get("create_from_expense", False)
        for rec in self:
            # TODO if we want to allow writeoff then we can disable this
            # constrain and send writeoff_journal_id and writeoff_acc_id
            if not rec.payment_ids:
                raise ValidationError(
                    _("You can not confirm a payment group without payment " "lines!")
                )
            # si el pago se esta posteando desde statements y hay doble
            # validacion no verificamos que haya deuda seleccionada
            if (
                rec.payment_subtype == "double_validation"
                and rec.payment_difference
                and (not create_from_statement and not create_from_expense)
            ):
                raise ValidationError(
                    _("To Pay Amount and Payment Amount must be equal!")
                )

            writeoff_acc_id = False
            writeoff_journal_id = False
            # if the partner of the payment is different of ht payment group we change it.
            rec.payment_ids.filtered(lambda p: p.partner_id != rec.partner_id).write(
                {"partner_id": rec.partner_id.id}
            )
            # al crear desde website odoo crea primero el pago y lo postea
            # y no debemos re-postearlo
            if not create_from_website and not create_from_expense:
                for payment_line in rec.payment_ids.filtered(lambda x: x.state == "draft"):
                    # esta solucion es medio chapuzera (x2) pero
                    # es la unica diponible. si el pago tiene otra moneda
                    # modifico el valor del rate de la moneda a la fecha
                    # para que cuando haga el asiento de diferencia de cambio
                    # Use la cotizacion del pago y no la de la moneda
                    # Luego vuelvo el rate al estado original :P 

                    old_rate = False
                    unlink_rate = False
                    if payment_line.other_currency:
                        old_rate, unlink_rate = payment_line.currency_id.sudo().set_temporal_rate(payment_line.date, 1/payment_line.exchange_rate)
                    payment_line.action_post()
                    if old_rate or unlink_rate:
                        payment_line.currency_id.sudo().unset_temporal_rate(payment_line.date,old_rate,unlink_rate)

            counterpart_aml = rec.payment_ids.mapped("line_ids").filtered(
                lambda r: not r.reconciled
                and r.account_id.internal_type in ("payable", "receivable")
            )

            # porque la cuenta podria ser no recivible y ni conciliable
            # (por ejemplo en sipreco)
            if counterpart_aml and rec.to_pay_move_line_ids:
                #Inicializo para variable no_exchange_difference
                #para que no genere asiento de diferencial cambiario
                #siempre y cuando la moneda del account.move.line su moneda
                #no sea distinta a la de la moneda base
                no_exchange_difference = True
                if not counterpart_aml.account_id.currency_id:
                    no_exchange_difference = True
                if counterpart_aml.account_id.currency_id:
                    if counterpart_aml.currency_id and counterpart_aml.currency_id != rec.company_id.currency_id:
                        #Si la moneda del account.move.line es diferente a la moneda
                        #de la company, valido que genere diferencial cambiarion 
                        #de perdia o ganancia, segun validacion nativa de odoo
                        no_exchange_difference = False
                (counterpart_aml + (rec.to_pay_move_line_ids)).with_context(no_exchange_difference=no_exchange_difference).reconcile()
            rec.state = "posted"
        return True

AccountPaymentGroup()