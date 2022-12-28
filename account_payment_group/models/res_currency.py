from ast import Return
from genericpath import exists
from odoo import  models, api
import logging
_logger = logging.getLogger(__name__)

class ResCurrency(models.Model):
    _inherit = "res.currency"

    def _convert(self, from_amount, to_currency, company, date, round=True):
        if self._context.get('force_rate_to', False):
            self, to_currency = self or to_currency, to_currency or self
            assert self, "convert amount from unknown currency"
            assert to_currency, "convert amount to unknown currency"
            assert company, "convert amount from unknown company"
            # apply conversion rate
            if self == to_currency:
                to_amount = from_amount
            else:
                to_amount = from_amount * self._context.get('force_rate_to', False)
            # apply rounding
            return to_currency.round(to_amount) if round else to_amount
        return super()._convert(from_amount, to_currency, company, date, round)

    def set_temporal_rate(self, date,new_rate):
        self.ensure_one()
        rate = self.rate_ids.filtered(lambda rate: rate.name==date)
        if len(rate):
            rate = sorted(rate, key=lambda r: r.id, reverse=True)[0]
            old_rate = rate.rate
            rate.rate = new_rate
            return old_rate, False
        else:
            self.env['res.currency.rate'].create({
                'name': date,
                'rate': new_rate,
                'currency_id': self.id
            })
            return 0, True

    def unset_temporal_rate(self, date, old_rate, unlink):
        self.ensure_one()
        rate = self.rate_ids.filtered(lambda rate: rate.name==date)

        if not unlink:
            rate.rate = old_rate
        else:
            rate.unlink()