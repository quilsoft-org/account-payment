{
    "name": "Payment Groups with Accounting Documents",
    "version": "14.0.1.1.0",
    "author": "ADHOC SA,Odoo Community Association (OCA), QUILSOFT",
    "license": "AGPL-3",
    "category": "Accounting",
    "depends": [
        "l10n_latam_invoice_document",
        "account_payment_group",
    ],
    "data": [
        'view/account_payment_group_view.xml',
        'view/account_payment_receiptbook_view.xml',
        'wizards/account_payment_group_invoice_wizard_view.xml',
        'security/ir.model.access.csv',
        'security/security.xml',
        # quitamos esto para que se pueda actualizar porque falla al intentar crear
        # el registro porque no encuentra el identificador externo
        #'data/decimal_precision_data.xml',
        'data/l10n_latam.document.type.csv',
    ],
    "demo": [
    ],
    'images': [
    ],
    'installable': True,
    'auto_install': False,
}
