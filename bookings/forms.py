from datetime import date

from django import forms

from catalog.models import EquipmentType, EquipmentUnit

from .services import BookingError, validate_period


class DateInput(forms.DateInput):
    """Поле дати з календарем браузера (<input type="date">)."""

    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class BookingForm(forms.Form):
    """Форма заявки: екземпляр і період оренди.

    Тут лише перевірка введених даних. Зайнятість екземпляра остаточно
    перевіряє services.create_booking разом з обмеженням у базі даних.
    """

    unit = forms.ModelChoiceField(
        label="Екземпляр",
        queryset=EquipmentUnit.objects.none(),
        empty_label=None,
    )
    start_date = forms.DateField(label="Дата видачі", widget=DateInput())
    end_date = forms.DateField(
        label="Дата повернення",
        widget=DateInput(),
        help_text="День повернення не оплачується і вже вільний для наступного клієнта.",
    )

    def __init__(self, *args, equipment_type: EquipmentType, **kwargs):
        super().__init__(*args, **kwargs)
        # Пропонуємо лише доступні екземпляри саме цього типу обладнання.
        self.fields["unit"].queryset = equipment_type.units.filter(
            status=EquipmentUnit.Status.AVAILABLE
        )
        self.fields["unit"].label_from_instance = lambda unit: f"Інв. № {unit.inventory_number}"
        # Підказка браузеру не пропонувати минулі дати (сервер однаково перевіряє сам).
        today = date.today().isoformat()
        for name in ("start_date", "end_date"):
            self.fields[name].widget.attrs["min"] = today

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end:
            try:
                validate_period(start, end)
            except BookingError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return cleaned
