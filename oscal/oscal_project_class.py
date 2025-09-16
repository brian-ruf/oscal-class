from loguru import logger
from common import *
from oscal_support_class import *
from oscal_content_class import *
import asyncio
import datetime

OSCAL_PROJECT_TABLES = {}
OSCAL_PROJECT_TABLES["project_files"] = {
    "table_name": "import_map",
    "table_fields": [
        {"name": "uuid"                , "type": "TEXT"   , "attributes": "PRIMARY KEY", "label": "Unique ID (Project-Assigned)"},
        {"name": "oscal_version"       , "type": "TEXT"   , "attributes": "", "label": "OSCAL Version"},
        {"name": "oscal_model"         , "type": "TEXT"   , "attributes": "", "label": "OSCAL Model"},
        {"name": "imports"             , "type": "TEXT"   , "attributes": "", "label": "Imports"},
        {"name": "xml_schema_valid"    , "type": "NUMERIC", "attributes": "", "label": "XML Schema Valid"},
        {"name": "json_schema_valid"   , "type": "NUMERIC", "attributes": "", "label": "JSON Schema Valid"},
        {"name": "metaschema_valid"    , "type": "NUMERIC", "attributes": "", "label": "Metaschema Valid"},
        {"name": "xml"                 , "type": "TEXT"   , "attributes": "", "label": "UUID of the XML version of the content if filecache"},
        {"name": "json"                , "type": "TEXT"   , "attributes": "", "label": "UUID of the JSON version of the content if filecache"},
        {"name": "yaml"                , "type": "TEXT"   , "attributes": "", "label": "UUID of the YAML version of the content if filecache"},
        {"name": "original"            , "type": "TEXT"   , "attributes": "", "label": "UUID of the original content if filecache"},
        {"name": "original_location"   , "type": "TEXT"   , "attributes": "", "label": "Original Content Location"},
        {"name": "original_format"     , "type": "TEXT"   , "attributes": "", "label": "Original Content Format"},
        {"name": "original_well_formed", "type": "NUMERIC", "attributes": "", "label": "Well Formed?"},
        {"name": "json_synced"         , "type": "NUMERIC", "attributes": "", "label": "Synced? (JSON Format)"},
        {"name": "yaml_synced"         , "type": "NUMERIC", "attributes": "", "label": "Synced? (YAML Format)"}
    ],
    "table_label": "Project Files",
    "table_description": "Information about the OSCAL files in this project."
}

OSCAL_PROJECT_TABLES["project_properties"] = {
    "table_name": "project_properties",
    "table_fields": [
        {"name": "uuid"                , "type": "TEXT"   , "attributes": "PRIMARY KEY", "label": "Unique ID (Project-Assigned)"},
        {"name": "name"                , "type": "TEXT"   , "attributes": "", "label": "Name"},
        {"name": "value"               , "type": "TEXT"   , "attributes": "", "label": "Value"},
        {"name": "remarks"             , "type": "TEXT"   , "attributes": "", "label": "Remarks"},
        {"name": "modified"            , "type": "TEXT"   , "attributes": "", "label": "Modified"}
    ],
    "table_label": "Project Properties",
    "table_description": "Information about the OSCAL project."
}

OSCAL_PROJECT_TABLES["snapshots"] = {
    "table_name": "snapshots",
    "table_fields": [
        {"name": "file_uuid"           , "type": "TEXT"   , "attributes": "KEY", "label": "Unique ID (Project-Assigned)"},
        {"name": "filecache_uuid"      , "type": "TEXT"   , "attributes": "KEY", "label": "Unique ID (Project-Assigned)"},
        {"name": "type"                , "type": "TEXT"   , "attributes": "", "label": "Snapshot Type"},
        {"name": "purpose"             , "type": "TEXT"   , "attributes": "", "label": "Purpose"},
        {"name": "created"             , "type": "TEXT", "attributes": "", "label": "Created"}
    ],
    "table_label": "Snapshots",
    "table_description": "Snapshots of project content."
}
OSCAL_PROJECT_TABLES["filecache"] = database.OSCAL_COMMON_TABLES["filecache"]

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# OSCAL PROJECT CLASS
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCAL_project:
    """
    OSCAL Class

    This class is used to manage the OSCAL project files and their contents.

    Parameters:
    - project_file: Path and file name of the project file.
                    - If None, an empty object will be returned,
                      and the new() method must be called to create 
                      a new project.
    
    Properties:

    
    Methods:
    - new(project_file): Create a new OSCAL project file.
    - load(): Load the project file and its contents.
    - save(): Save the project file and its contents.
    - show_stack(): Show the stack of project files.

    """
    def __init__(self, db_conn, db_type="sqlite3"):
        self.project_file = "" # Path and file name of the project file
        self.project_files = {}
        self.properties = {}

        self.ready      = False     # Is the project capability available?
        self.db_conn    = db_conn   # The project database connection string or path and filename 
        self.db_type    = db_type   # The project database type (sqlite3, mysql, postgresql, mssql, etc.)
        self.db_state   = "unknown" # The state of the project database (unknown, not-present, empty, populated)
        self.backend    = None      # If working within an application, this is the backend object

        self.properties = {
            "title"                 : {"value" : "New Project", "remarks" : "Title of the project"},
            "description"           : {"value" : "", "remarks" : "Description of the project"},
            "created"               : {"value" : misc.oscal_date_time_with_timezone(), "remarks" : "Date and time the project was created"},
            "modified"              : {"value" : misc.oscal_date_time_with_timezone(), "remarks" : "Date and time the project was last modified"}
        }

        self.db = database.Database(self.db_type, self.db_conn)
        if self.db is not None:
            asyncio.create_task(self.async_init())
        else:
            logger.error("Unable to create project database object.")
            self.ready = False
    # -------------------------------------------------------------------------
    async def async_init(self):
        self.ready = await self.startup()
    # -------------------------------------------------------------------------
    @classmethod
    async def create(cls, db_conn, db_type="sqlite3"):
        """Async factory method to create and initialize the project database."""
        self = cls(db_conn, db_type)
        status = False
        if self.db is not None:
            self.ready = await self.startup()
            if self.ready:
                # Populate the project properties
                status = await self.__save_properties()
        
        return self
    # -------------------------------------------------------------------------
    async def startup(self, check_for_updates=False, refresh_all=False):
        """
        Perform startup tasks required to provide OSCAL support.

        1 Check for tables
          - If tables do not exist:
            - create tables
            - set state to "empty"
          - If tables exist, check for data
            - If no data, set state to "empty"
            - If data exists, set state to "populated"
        2 If state is "empty", get the OSCAL file
        3 If state is "populated" set self.ready to True
        """
        status = False
        if self.db_state == "unknown": 
            status = await self.db.check_for_tables(OSCAL_PROJECT_TABLES)

            if status: # Tables exist
                status = await self.load_project()
                if status:
                    self.db_state = "populated"
                    self.ready = True
                else:
                    self.db_state = "empty"
            else:
                logger.error("Unable to initiate OSCAL project capability. Exiting.")
                self.ready = False

        if self.db_state == "empty":
            status = await self.new()

            if status:
                self.db_state = "populated"
                self.ready = True
            else:
                logger.error("Unable to update OSCAL support capability. Exiting.")
                self.ready = False
       
        return status
    # -------------------------------------------------------------------------
    async def load_project(self):
        """
        Load the OSCAL stack into memory.
        """
        status = True
        return status
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    def new(self, project_file):
        """
        Create a new OSCAL project at the file location.
        Parameters:
        - project_file: Path and file name of the project file.

        """
        self.project_file = project_file
        pass

    # -------------------------------------------------------------------------
    @classmethod
    async def load(cls, project_file):
        """
        Load the OSCAL project file and its contents.
        Parameters:
        - project_file: Path and file name of the project file.

        """
        self = cls(project_file)
        if self.db is not None:
            self.ready = await self.startup()
        return self

    # -------------------------------------------------------------------------
    def save(self):
        """
        Save the project file and its contents.
        """
        pass
    # -------------------------------------------------------------------------
    def show_oscal_stack(self):
        """
        Show the stack of project files.
        """
        pass

    # -------------------------------------------------------------------------
    def oscal_import(self, file):
        """
        Import a file into the project.
        """
        pass
    # -------------------------------------------------------------------------
    def refresh_oscal_stack(self):
        """
        Refresh the import stack.
        """
        pass

    # -------------------------------------------------------------------------
    async def __load_properties(self):
        """
        Loads the project properties from the project_properties table into a JSON structure.
        """
        logger.debug("Loading project properties from database.")
        status = False

        query = "SELECT * FROM project_properties"
        results = await self.db.query(query)
        if results is not None:
            for entry in results:
                self.properties[entry["name"]] = {
                    "uuid"          : entry.get("uuid", ""),
                    "value"         : entry.get("value", ""),
                    "remarks"       : entry.get("remarks", "")
                }
            status = True

        return status

    # -------------------------------------------------------------------------
    async def __save_properties(self):
        """
        Saves the project properties from the JSON structure to a project_properties table.
        """
        logger.debug("Saving project properties to database.")
        status = True

        sql_commands = []
        # logger.debug(f"Properties: {json.dumps(self.properties)}")
        # Cycle through the properties and save them to the database
        for key, value in self.properties.items():
            logger.debug(f"Saving property: {key} = {value}")
            if "uuid" in value:
                # Update the existing record
                sql_commands.append( f"UPDATE project_properties SET value='{value['value']}', remarks='{value['remarks']}' WHERE uuid='{value['uuid']}'" )
            else:
                # Insert a new record
                value["uuid"] = str(uuid.uuid4())
                sql_commands.append( f"INSERT INTO project_properties (uuid, name, value, remarks) VALUES ('{value['uuid']}', '{key}', '{value['value']}', '{value['remarks']}')")
        result = await self.db.db_execute(sql_commands)

        if not result:
            logger.error(f"Unable to save \"{key}\" document property to project database. (UUID: ({value['uuid']}))")
            status = status and result

        return status

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~



# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


if __name__ == '__main__':
    print("OSCAL Project Class Library. Not intended to be run as a stand-alone file.")

