import os
from dotenv import load_dotenv
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

load_dotenv()

GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")


class BigQueryClient:
    """
    Client for connecting to and querying Google BigQuery.

    Environment variables:
      GOOGLE_CLOUD_PROJECT          — default GCP project ID
      GOOGLE_APPLICATION_CREDENTIALS — optional path to service account key JSON
    """

    def __init__(self,
                 project: str=None,
                 credentials_path: str=None):
        self.project = project or GOOGLE_CLOUD_PROJECT
        credentials_path = credentials_path or GOOGLE_APPLICATION_CREDENTIALS

        if credentials_path:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            self.client = bigquery.Client(project=self.project, credentials=credentials)
        else:
            # Falls back to Application Default Credentials (ADC) 
            self.client = bigquery.Client(project=self.project)

    # ------------------------------------------------------------------
    # Datasets
    # ------------------------------------------------------------------

    def list_datasets(self) -> list[str]:
        """Return a list of dataset IDs in the project."""
        return [ds.dataset_id for ds in self.client.list_datasets()]

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    def list_tables(self, dataset: str) -> list[str]:
        """Return a list of table IDs in *dataset*."""
        dataset_ref = self.client.dataset(dataset)
        return [t.table_id for t in self.client.list_tables(dataset_ref)]

    def get_table(self, dataset: str, table: str) -> bigquery.Table:
        """
        Return the full BigQuery Table object 
        (includes schema, metadata, etc.).
        """
        table_ref = self.client.dataset(dataset).table(table)
        return self.client.get_table(table_ref)

    def table_schema(self, dataset: str, table: str) -> pd.DataFrame:
        """
        Return the schema of *table* as a DataFrame with columns:
        name, field_type, mode.
        """
        tbl = self.get_table(dataset, table)
        return pd.DataFrame(
            [{"name": f.name,
              "field_type": f.field_type,
              "mode": f.mode} for f in tbl.schema]
        )

    def table_info(self, dataset: str, table: str) -> dict:
        """Return a summary dict of table metadata (row count, size, created, modified)."""
        tbl = self.get_table(dataset, table)
        return {
            "project": tbl.project,
            "dataset": tbl.dataset_id,
            "table": tbl.table_id,
            "full_table_id": f"{tbl.project}.{tbl.dataset_id}.{tbl.table_id}",
            "num_rows": tbl.num_rows,
            "num_bytes": tbl.num_bytes,
            "created": tbl.created,
            "modified": tbl.modified,
            "description": tbl.description,
        }

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def query(self, sql: str, params: list = None) -> pd.DataFrame:
        """
        Run *sql* and return results as a DataFrame.

        Parameters
        ----------
        sql    : standard SQL string; use @param_name for named parameters
        params : optional list of bigquery.ScalarQueryParameter objects
        """
        job_config = bigquery.QueryJobConfig(query_parameters=params or [])
        job = self.client.query(sql, job_config=job_config)
        return job.result().to_dataframe()

    def preview_table(self,
                      dataset: str,
                      table: str,
                      limit: int=10) -> pd.DataFrame:
        """Return the first *limit* rows of *table* as a DataFrame."""
        full_id = f"`{self.project}.{dataset}.{table}`"
        return self.query(f"SELECT * FROM {full_id} LIMIT {limit}")

    def count_rows(self, dataset: str, table: str) -> int:
        """Return the approximate row count for *table* (from metadata, no query cost)."""
        return self.get_table(dataset, table).num_rows

    def select_single_table(self,
                            dataset: str,
                            table_name: str,
                            column_names: list[str] = ["*"],
                            condition: str=None,
                            num: int=None) -> pd.DataFrame:
        """
        SELECT specific columns from a single table with an optional WHERE condition.

        Parameters
        ----------
        dataset      : BigQuery dataset ID
        table_name   : table ID within the dataset
        column_names : columns to select (default ["*"] = all columns)
        condition    : raw SQL expression placed after WHERE, e.g.
                       "state = 'CA' AND year >= 2020"
        """
        full_id = f"`{self.project}.{dataset}.{table_name}`"
        cols = ", ".join(column_names)
        sql = f"SELECT {cols} FROM {full_id}"
        if condition:
            sql += f" WHERE {condition}"
        if num:
            sql += f" LIMIT {num}"
        return self.query(sql)