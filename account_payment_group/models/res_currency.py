from odoo import  models
import logging
_logger = logging.getLogger(__name__)

class ResCurrency(models.Model):
    _inherit = "res.currency"

    def _convert(self, from_amount, to_currency, company, date, round=True):
        _logger.info('_convert')
        _logger.info(self.env.context)

        if self._context.get('force_rate_to', False):
            _logger.info('force_rate_to')
            _logger.info(self._context.get('force_rate_to', False))
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
            _logger.info(to_amount)
            return to_currency.round(to_amount) if round else to_amount
        return super()._convert(from_amount, to_currency, company, date, round)
