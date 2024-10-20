import logging
from typing import Dict, Sequence

from sqlalchemy import select

from hdx.api.configuration import Configuration
from hdx.database import Database
from hdx.location.country import Country
from hdx.utilities.dateparse import (
    iso_string_from_datetime,
)

from .country_dataset import CountryDataset

logger = logging.getLogger(__name__)


class SubcategoryReader:
    def __init__(
        self,
        configuration: Configuration,
        database: Database,
    ):
        self.configuration = configuration
        self.session = database.get_session()
        self.views = database.get_prepare_results()
        view = self.views["resource"]
        results = self.session.execute(
            select(view.c.hdx_id, view.c.dataset_hdx_provider_name)
        ).all()
        self.resource_hdx_id_to_hdx_provider_name = {
            hdx_id: dataset_hdx_provider_name
            for hdx_id, dataset_hdx_provider_name in results
        }

    def get_all_countries(self) -> Sequence:
        view = self.views["data_availability"]
        countryiso3s = []
        for countryiso3 in self.session.scalars(
            select(view.c.location_code).distinct()
        ).all():
            country_info = Country.get_country_info_from_iso3(countryiso3)
            if country_info["#indicator+incomelevel"].lower() == "high":
                continue
            countryiso3s.append(countryiso3)
        return sorted(countryiso3s)

    def view_by_location(
        self,
        country_dataset: CountryDataset,
        subcategory_info: Dict,
        countryiso3: str,
    ) -> bool:
        view_name = subcategory_info["view"]
        logger.info(f"Processing subcategory {view_name}")
        view = self.views[subcategory_info["view"]]
        headers_to_index = {col.name: i for i, col in enumerate(view.c)}
        if "origin_location_code" in headers_to_index:
            results = self.session.execute(
                select(view).where(
                    view.c.origin_location_code == countryiso3
                    or view.c.asylum_location_code == countryiso3
                )
            )
        else:
            results = self.session.execute(
                select(view).where(view.c.location_code == countryiso3)
            )

        hxltags = subcategory_info["hxltags"]
        rows = []
        for result in results:
            index = headers_to_index.get("resource_hdx_id")
            if index is not None:
                resource_hdx_id = result[index]
                dataset_provider_name = (
                    self.resource_hdx_id_to_hdx_provider_name[resource_hdx_id]
                )
                country_dataset.add_sources(dataset_provider_name)
            row = {}
            for header, hxltag in hxltags.items():
                value = result[headers_to_index[header]]
                if hxltag == "#date+start":
                    country_dataset.update_start_date(value)
                    value = iso_string_from_datetime(value)
                elif hxltag == "#date+end":
                    country_dataset.update_end_date(value)
                    value = iso_string_from_datetime(value)
                row[header] = str(value)
            rows.append(row)
        if len(rows) == 0:
            return False
        country_dataset.add_tags(subcategory_info["tags"])
        resource_info = subcategory_info["resource"]
        return country_dataset.add_resource(resource_info, hxltags, rows)
