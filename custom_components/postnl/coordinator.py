import asyncio
import logging
from datetime import timedelta

import requests
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (DataUpdateCoordinator,
                                                      UpdateFailed)

from . import AsyncConfigEntryAuth, PostNLGraphql
from .const import DOMAIN
from .jouw_api import PostNLJouwAPI
from .structs.package import Package

_LOGGER = logging.getLogger(__name__)


class PostNLCoordinator(DataUpdateCoordinator):
    data: dict[str, list[Package]]
    graphq_api: PostNLGraphql
    jouw_api: PostNLJouwAPI

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize PostNL coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="PostNL",
            update_interval=timedelta(seconds=90),
        )

    async def _async_update_data(self) -> dict[str, list[Package]]:
        _LOGGER.debug('Starting data update for PostNL.')
        try:
            auth: AsyncConfigEntryAuth = self.hass.data[DOMAIN][self.config_entry.entry_id]['auth']
            _LOGGER.debug('Checking and refreshing authentication token.')
            await auth.check_and_refresh_token()

            self.graphq_api = PostNLGraphql(auth.access_token)
            self.jouw_api = PostNLJouwAPI(auth.access_token)

            data: dict[str, list[Package]] = {
                'receiver': [],
                'sender': []
            }

            _LOGGER.debug('Fetching shipments from GraphQL API.')
            shipments = await self.hass.async_add_executor_job(self.graphq_api.shipments)

            receiver_shipments = [self.transform_shipment(shipment) for shipment in
                                  shipments.get('trackedShipments', {}).get('receiverShipments', [])]
            data['receiver'] = await asyncio.gather(*receiver_shipments)
            _LOGGER.debug('Processed %d receiver shipments.', len(data['receiver']))

            sender_shipments = [self.transform_shipment(shipment) for shipment in
                                shipments.get('trackedShipments', {}).get('senderShipments', [])]
            data['sender'] = await asyncio.gather(*sender_shipments)
            _LOGGER.debug('Processed %d sender shipments.', len(data['sender']))

            _LOGGER.debug('Total packages processed: %d', len(data['sender']) + len(data['receiver']))

            return data
        except requests.exceptions.RequestException as exception:
            raise UpdateFailed("Unable to update PostNL data") from exception

    async def transform_shipment(self, shipment) -> Package:
        _LOGGER.debug('Transforming shipment with key: %s', shipment.get('key'))

        try:
            if shipment.get('delivered'):
                _LOGGER.debug('Shipment %s already delivered. Skipping API call.', shipment.get('key'))

                return Package(
                    key=shipment.get('key'),
                    name=shipment.get('title'),
                    url=shipment.get('detailsUrl'),
                    shipment_type=shipment.get('shipmentType'),
                    status_message="Pakket is bezorgd",
                    delivered=shipment.get('delivered'),
                    delivery_date=shipment.get('deliveredTimeStamp'),
                    delivery_address_type=shipment.get('deliveryAddressType')
                )

            _LOGGER.debug('Fetching track and trace details for shipment: %s', shipment.get('key'))
            track_and_trace_details = await self.hass.async_add_executor_job(self.jouw_api.track_and_trace, shipment['key'])

            if not track_and_trace_details or 'colli' not in track_and_trace_details:
                _LOGGER.warning('No colli data found for shipment: %s. Raw data: %s', shipment.get('key'), track_and_trace_details)
                _LOGGER.debug(track_and_trace_details)
                colli = None
            else:
                colli = track_and_trace_details['colli'].get(shipment['barcode'], None)

            if colli:
                _LOGGER.debug('Colli data found for shipment: %s', shipment.get('key'))
                route_information = colli.get("routeInformation", None)
                if route_information:
                    planned_date = route_information.get("plannedDeliveryTime", None)
                    planned_from = route_information.get("plannedDeliveryTimeWindow", {}).get("startDateTime", None)
                    planned_to = route_information.get("plannedDeliveryTimeWindow", {}).get("endDateTime", None)
                    expected_datetime = route_information.get("expectedDeliveryTime", None)
                else:
                    _LOGGER.debug("Route information is None, using fallback values.")
                    planned_date = shipment.get('deliveryWindowFrom', None)
                    planned_from = shipment.get('deliveryWindowFrom', None)
                    planned_to = shipment.get('deliveryWindowTo', None)
                    expected_datetime = None

                status_phase = colli.get('statusPhase', None)
                status_message = status_phase.get('message', "Unknown") if isinstance(status_phase, dict) else "Unknown"
            else:
                _LOGGER.debug('Colli is None for shipment: %s, falling back to shipment data.', shipment.get('key'))
                planned_date = shipment.get('deliveryWindowFrom', None)
                planned_from = shipment.get('deliveryWindowFrom', None)
                planned_to = shipment.get('deliveryWindowTo', None)
                expected_datetime = None
                status_message = "Unknown"

            return Package(
                key=shipment.get('key'),
                name=shipment.get('title'),
                url=shipment.get('detailsUrl'),
                shipment_type=shipment.get('shipmentType'),
                status_message=colli.get('statusPhase', {}).get('message', "Unknown"),
                delivered=shipment.get('delivered'),
                delivery_date=shipment.get('deliveredTimeStamp'),
                delivery_address_type=shipment.get('deliveryAddressType'),
                planned_date=planned_date,
                planned_from=planned_from,
                planned_to=planned_to,
                expected_datetime=expected_datetime
            )
        except requests.exceptions.RequestException as exception:
            _LOGGER.error('Failed to process shipment %s: %s', shipment.get('key'), exception)
            raise UpdateFailed("Unable to update PostNL data") from exception
