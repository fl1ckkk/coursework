"""Вмикає розширення PostgreSQL btree_gist.

Воно потрібне для обмеження EXCLUDE у міграції 0003: GiST-індекс має
порівнювати і діапазон дат (&&), і звичайне ціле поле unit_id (=).
Без btree_gist GiST не вміє оператор = для цілих чисел.
Детальний опис: documentation/migrations/bookings_0002_btree_gist_extension.md
"""

from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0001_initial"),
    ]

    operations = [
        BtreeGistExtension(),
    ]
