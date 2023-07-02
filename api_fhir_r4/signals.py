from typing import Union, List, Tuple, Iterable

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

import core.datetimes.ad_datetime
from api_fhir_r4.converters import BaseFHIRConverter, ReferenceConverterMixin
from api_fhir_r4.models import Subscription, SubscriptionNotificationResult
from api_fhir_r4.subscriptions.notificationClient import RestSubscriptionNotificationClient, \
    SubscriberNotificationOutput
from core.models import HistoryModel, VersionedModel

import logging
import requests
import json
from django.core.exceptions import ObjectDoesNotExist

from api_fhir_r4.converters import PatientConverter, BillInvoiceConverter, InvoiceConverter, \
    HealthFacilityOrganisationConverter
from api_fhir_r4.mapping.invoiceMapping import InvoiceTypeMapping, BillTypeMapping
from api_fhir_r4.subscriptions.notificationManager import RestSubscriptionNotificationManager
from api_fhir_r4.subscriptions.subscriptionCriteriaFilter import SubscriptionCriteriaFilter
from core.service_signals import ServiceSignalBindType
from core.signals import bind_service_signal
from api_fhir_r4.converters import BaseFHIRConverter, ReferenceConverterMixin

from openIMIS.openimisapps import openimis_apps


logger = logging.getLogger('openIMIS')
imis_modules = openimis_apps()


def bind_service_signals():
    if 'insuree' in imis_modules:
        def on_insuree_create_or_update(**kwargs):
            model = kwargs.get('result', None)
            if model:
                fhir_content = _resource_to_fhirr(model)
                url= 'https://ptsv3.com/t/giuy/'
                headers = {'Content-Type': 'application/json'}
                response = requests.post(url, headers=headers, data=fhir_content)
                
        bind_service_signal(
            'insuree_service.create_or_update',
            on_insuree_create_or_update,
            bind_type=ServiceSignalBindType.AFTER
        )
                
        bind_service_signal(
            'insuree_service.create_or_update',
            on_insuree_create_or_update,
            bind_type=ServiceSignalBindType.AFTER
        )

    def _resource_to_fhirr(imis_resource: Union[HistoryModel, VersionedModel]) -> dict:
        return PatientConverter().to_fhir_obj(imis_resource, ReferenceConverterMixin.UUID_REFERENCE_TYPE).dict()

    
    if 'location' in imis_modules:
        def on_hf_create_or_update(*args, **kwargs):
            model = kwargs.get('result', None)
            if model:
                notify_subscribers(model, HealthFacilityOrganisationConverter(), 'Organisation', 'bus')

        bind_service_signal(
            'health_facility_service.update_or_create',
            on_hf_create_or_update,
            bind_type=ServiceSignalBindType.AFTER
        )
    
    if 'invoice' in imis_modules:
        from invoice.models import Bill, Invoice

        def on_bill_create(**kwargs):
            result = kwargs.get('result', {})
            if result and result.get('success', False):
                model_uuid = result['data']['uuid']
                try:
                    model = Bill.objects.get(uuid=model_uuid)
                    notify_subscribers(model, BillInvoiceConverter(), 'Invoice',
                                       BillTypeMapping.invoice_type[model.subject_type.model])
                except ObjectDoesNotExist:
                    logger.error(f'Bill returned from service does not exists ({model_uuid})')
                    import traceback
                    logger.debug(traceback.format_exc())

        def on_invoice_create(**kwargs):
            result = kwargs.get('result', {})
            if result and result.get('success', False):
                model_uuid = result['data']['uuid']
                try:
                    model = Invoice.objects.get(uuid=model_uuid)
                    notify_subscribers(model, InvoiceConverter(), 'Invoice',
                                       InvoiceTypeMapping.invoice_type[model.subject_type.model])
                except ObjectDoesNotExist:
                    logger.error(f'Invoice returned from service does not exists ({model_uuid})')
                    import traceback
                    logger.debug(traceback.format_exc())

        bind_service_signal(
            'signal_after_invoice_module_bill_create_service',
            on_bill_create,
            bind_type=ServiceSignalBindType.AFTER
        )
        bind_service_signal(
            'signal_after_invoice_module_invoice_create_service',
            on_invoice_create,
            bind_type=ServiceSignalBindType.AFTER
        )


def notify_subscribers(model, converter, resource_name, resource_type_name):
    try:
        subscriptions = SubscriptionCriteriaFilter(model, resource_name,
                                                   resource_type_name).get_filtered_subscriptions()
        RestSubscriptionNotificationManager(converter).notify_subscribers_with_resource(model, subscriptions)
    except Exception as e:
        logger.error(f'Notifying subscribers failed: {e}')
        import traceback
        logger.debug(traceback.format_exc())
