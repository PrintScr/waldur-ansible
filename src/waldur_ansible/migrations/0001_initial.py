# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-06-09 17:30
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import django_fsm
import model_utils.fields
import waldur_core.core.fields
import waldur_core.core.validators
import re


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('structure', '0052_customer_subnets'),
    ]

    operations = [
        migrations.CreateModel(
            name='Job',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('description', models.CharField(blank=True, max_length=500, verbose_name='description')),
                ('name', models.CharField(max_length=150, validators=[waldur_core.core.validators.validate_name], verbose_name='name')),
                ('uuid', waldur_core.core.fields.UUIDField()),
                ('arguments', waldur_core.core.fields.JSONField(blank=True, default={}, null=True)),
                ('output', models.TextField(blank=True)),
                ('state', django_fsm.FSMIntegerField(choices=[(1, 'Scheduled'), (2, 'Executing'), (3, 'OK'), (4, 'Erred')], default=1)),
            ],
        ),
        migrations.CreateModel(
            name='Playbook',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('description', models.CharField(blank=True, max_length=500, verbose_name='description')),
                ('name', models.CharField(max_length=150, validators=[waldur_core.core.validators.validate_name], verbose_name='name')),
                ('uuid', waldur_core.core.fields.UUIDField()),
                ('workspace', models.CharField(help_text='Absolute path to the playbook workspace.', max_length=255, unique=True)),
                ('entrypoint', models.CharField(help_text='Relative path to the file in the workspace to execute.', max_length=255)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='PlaybookParameter',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('description', models.CharField(blank=True, max_length=500, verbose_name='description')),
                ('name', models.CharField(help_text='Required. 255 characters or fewer. Letters, numbers and _ characters', max_length=255, validators=[django.core.validators.RegexValidator(re.compile('^[\\w]+$'), 'Enter a valid name.')])),
                ('required', models.BooleanField(default=False)),
                ('default', models.CharField(blank=True, help_text='Default argument for this parameter.', max_length=255)),
                ('playbook', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='parameters', to='waldur_ansible.Playbook')),
            ],
        ),
        migrations.AddField(
            model_name='job',
            name='playbook',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='jobs', to='waldur_ansible.Playbook'),
        ),
        migrations.AddField(
            model_name='job',
            name='project',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='structure.Project'),
        ),
        migrations.AlterUniqueTogether(
            name='playbookparameter',
            unique_together=set([('playbook', 'name')]),
        ),
    ]
