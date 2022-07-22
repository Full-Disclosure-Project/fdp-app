# Generated by Django 3.1.14 on 2022-07-22 14:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_auto_20220721_1920'),
    ]

    operations = [
        migrations.RenameField(
            model_name='grouping',
            old_name='is_inactive',
            new_name='ended_unknown_date',
        ),
        migrations.RenameField(
            model_name='persongrouping',
            old_name='is_inactive',
            new_name='ended_unknown_date',
        ),
        migrations.AlterField(
            model_name='grouping',
            name='ended_unknown_date',
            field=models.BooleanField(default=False,
                                      help_text="Select if the grouping is no longer active. Instead of deleting a group, mark it as inactive so that all the data relating to the group and the group history remains. This can also be used if you don't know the ceased date for a group but you know that they are no longer active.",
                                      verbose_name='ended at unknown date'),
        ),
        migrations.AlterField(
            model_name='persongrouping',
            name='ended_unknown_date',
            field=models.BooleanField(default=False,
                                      help_text='Select if the person is no longer associate with group but the end date is unknown',
                                      verbose_name='ended at unknown end date'),
        ),
    ]
