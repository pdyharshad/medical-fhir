# Copyright 2020 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


class MedicalQuestionnaireResponse(models.Model):

    _name = "medical.questionnaire.response"
    _description = "Medical Questionnaire Response"  # TODO
    _inherit = ["medical.event", "certify.base"]

    questionnaire_id = fields.Many2one(
        "medical.questionnaire", required=True, track_visibility="onchange",
    )
    procedure_request_id = fields.Many2one(
        comodel_name="medical.procedure.request",
        string="Procedure request",
        ondelete="restrict",
        index=True,
        readonly=True,
    )  # FHIR Field: BasedOn
    item_ids = fields.One2many(
        "medical.questionnaire.response.item",
        inverse_name="questionnaire_response_id",
    )

    def _generate_serializer(self):
        res = super()._generate_serializer()
        res.update(
            {
                "patient_id": self.patient_id.id,
                "item_ids": [
                    {"id": item.id, "name": item.name, "result": item.result}
                    for item in self.item_ids
                ],
            }
        )
        return res

    def _get_internal_identifier(self, vals):
        return (
            self.env["ir.sequence"].next_by_code(
                "medical.questionnaire.response"
            )
            or "/"
        )

    def in_progress2completed(self):
        for record in self:
            if not record.questionnaire_id.check_code:
                continue
            data = {}
            for item in record.item_ids:
                item_name = item.questionnaire_item_id.technical_name
                if not item_name:
                    continue
                data[item_name] = item._transform_result(item.result)
            if not safe_eval(record.questionnaire_id.check_code, data):
                raise ValidationError(
                    _("Questionnaire %s is not correctly fullfilled")
                    % record.display_name
                )
        res = super().in_progress2completed()
        for record in self:
            for item in record.item_ids:
                if not item.questionnaire_item_id.destination_field:
                    continue
                dest = item.questionnaire_item_id.destination_field.split(".")
                dest_field = dest[-1]
                data = record
                for destination in dest[:-1]:
                    if hasattr(data, destination):
                        data = getattr(data, destination)
                    else:
                        raise ValidationError(
                            _("Field %s cannot be found on %s")
                            % (destination, data._name)
                        )
                if hasattr(data, dest_field):
                    data.write(
                        {dest_field: item._transform_result(item.result)}
                    )
                else:
                    raise ValidationError(
                        _("Field %s cannot be found on %s")
                        % (dest_field, data._name)
                    )
            record._sign_document()
        return res

    def preparation2in_progress(self):
        for response in self:
            for item in response.questionnaire_id.item_ids:
                item._generate_question(response)
        super().preparation2in_progress()

    def back_to_draft(self):
        for response in self:
            response.item_ids.unlink()
        self.write({"state": "preparation"})

    def fill_questionnaire(self):
        ctx = self.env.context.copy()
        ctx["widget_medical_questionnaire"] = True
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": self._name,
            "res_id": self.id,
            "target": "new",
            "view_mode": "form",
            "context": ctx,
            "views": [
                (
                    self.env.ref(
                        "medical_clinical_questionnaire."
                        "medical_questionnaire_response_fill_form_view"
                    ).id,
                    "form",
                )
            ],
        }

    def _generate_from_request_vals(self, request):
        return {
            "procedure_request_id": request.id,
            "service_id": request.service_id and request.service_id.id,
            "patient_id": request.patient_id.id,
            "performer_id": request.performer_id and request.performer_id.id,
            "questionnaire_id": request.questionnaire_id.id,
        }

    def _generate_from_request(self, request):
        return self.create(self._generate_from_request_vals(request))


class MedicalQuestionnaireResponseItem(models.Model):
    _name = "medical.questionnaire.response.item"
    _description = "Questionnaire Response item"

    questionnaire_response_id = fields.Many2one(
        "medical.questionnaire.response", required=True,
    )
    name = fields.Char(required=True, readonly=True)
    required = fields.Boolean(default=True, readonly=True)
    question_type = fields.Selection(
        selection=lambda r: r.env[
            "medical.questionnaire.item"
        ]._get_questionnaire_item_type(),
        required=True,
        readonly=True,
    )
    result = fields.Text()
    selection_options = fields.Char()
    options = fields.Char()
    questionnaire_item_id = fields.Many2one(
        "medical.questionnaire.item", readonly=False,
    )
    technical_name = fields.Char(
        related="questionnaire_item_id.technical_name",
    )
    readonly = fields.Boolean(related="questionnaire_item_id.readonly")
    readonly_condition = fields.Char(
        related="questionnaire_item_id.readonly_condition",
    )
    is_invisible = fields.Boolean(related="questionnaire_item_id.is_invisible")
    invisible_condition = fields.Char(
        related="questionnaire_item_id.invisible_condition",
    )

    def read(self, fields=None, load="_classic_read"):
        result = super().read(fields=fields, load=load)
        if not self.env.context.get("widget_medical_questionnaire"):
            return result
        for r in result:
            if "result" in r:
                record = self.browse(r["id"])
                r["result"] = record._transform_result(record.result)
        return result

    def _transform_result(self, result):
        if self.question_type == "integer":
            return int(result)
        if self.question_type == "float":
            return float(result)
        if self.question_type == "boolean":
            return bool(result)
        if self.question_type == "date":
            return fields.Datetime.from_string(result)
        return result

    def write(self, vals):
        for rec in self:
            vals.pop("result_%s" % rec.id, False)
        return super().write(vals)