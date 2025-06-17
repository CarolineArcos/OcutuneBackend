# schemas/auth_schema.py

from marshmallow import Schema, fields

class LoginSchema(Schema):
    sim_userid   = fields.String(required=True)
    sim_password = fields.String(required=True)
