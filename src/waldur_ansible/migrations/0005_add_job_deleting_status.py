# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-10-18 16:42
from __future__ import unicode_literals

from django.db import migrations, models
import django_fsm


class Migration(migrations.Migration):

    dependencies = [
        ('waldur_ansible', '0004_add_spl_key_subnet_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='error_message',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='job',
            name='state',
            field=django_fsm.FSMIntegerField(choices=[(5, 'Creation Scheduled'), (6, 'Creating'), (1, 'Update Scheduled'), (2, 'Updating'), (7, 'Deletion Scheduled'), (8, 'Deleting'), (3, 'OK'), (4, 'Erred')], default=5),
        ),
    ]
