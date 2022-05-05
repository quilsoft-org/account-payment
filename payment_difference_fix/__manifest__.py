{
    "name": "Payment Difference Fix",
    "summary": """El sistema no estaba realizando los asientos por diferencia de cambio
        en forma automática. Se corrige con este fix""",
    "description": """
        Corrije bug en diferencia de cambio
    """,
    "author": "Quilsoft",
    "website": "http://www.quilsoft.com",
    "category": "Payments",
    "version": "14.0.3.0.0",
    "depends": [
        "base",
        "account",
        "account_ux",
        "account_payment_group",
    ],
    'auto_install': True,
}
