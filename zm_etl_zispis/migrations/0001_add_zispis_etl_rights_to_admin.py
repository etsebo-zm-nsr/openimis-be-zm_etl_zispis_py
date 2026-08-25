from django.db import migrations

# Per-connector trigger right, so "may run the ZISPIS sync" can be granted independently
# of any other ETL source.
zispis_rights = [953101]
imis_administrator_system = 64


def add_rights(apps, schema_editor):
    role_model = apps.get_model('core', 'role')
    role = role_model.objects.filter(is_system=imis_administrator_system).first()
    if role is None:
        return
    for right_id in zispis_rights:
        if not apps.get_model('core', 'roleright').objects.filter(
                validity_to__isnull=True, role=role, right_id=right_id).exists():
            apps.get_model('core', 'roleright').objects.create(
                role=role, right_id=right_id, audit_user_id=1)


def remove_rights(apps, schema_editor):
    apps.get_model('core', 'roleright').objects.filter(
        role__is_system=imis_administrator_system,
        right_id__in=zispis_rights,
        validity_to__isnull=True
    ).delete()


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        # core.0002 adds `layer`/`is_exposed` to ModuleConfiguration and is the safe
        # floor for touching core models from a data migration.
        ('core', '0002_auto_20190726_0701'),
    ]

    operations = [
        migrations.RunPython(add_rights, remove_rights),
    ]
