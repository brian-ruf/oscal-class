"""
SQLite3 Functions: Functions that are specific to use of SQLite3. ---
These functions assume that the SQLite3 database is already created and
"""
import os
import logging
import pickle
from typing import Any, Optional, Dict
import zlib
import sqlite3
from .helper import convert_datetime_format

logger = logging.getLogger(__name__)

FILE_CACHE_TABLE = 'filecache'

def save_to_db(conn: sqlite3.Connection, table_name: str, content: Any, identifier: Optional[str] = None, 
               additional_fields: Optional[Dict] = None) -> str:
    """
    Save content and additional fields to a SQLite database with type preservation.
    If an identifier is provided, the record will be updated if it already exists.
    
    Args:
        conn: SQLite connection object
        table_name: Name of the table to store the content
        content: The content to store (can be any Python data type)
        identifier: Optional UUID for updating existing records
        additional_fields: Optional dictionary of field names and values to store
    
    Returns:
        str: The UUID of the saved record, or empty string if table doesn't exist
    """
    cursor = conn.cursor()
    
    try:
        # Check if table exists
        cursor.execute(f"PRAGMA table_info({table_name})")
        table_columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        if not table_columns:
            logger.error(f"Table '{table_name}' does not exist in the database")
            return ""
        
        # Generate UUID if none provided
        if identifier is None:
            import uuid
            identifier = str(uuid.uuid4())
        
        # Serialize the content
        serialized_content = pickle.dumps(content)
        content_type = type(content).__name__
        
        # Prepare the base data
        field_names = ['uuid', 'content', 'datatype']
        field_values = [identifier, serialized_content, content_type]
        
        # Add additional fields if they exist in the table
        if additional_fields:
            for field_name in table_columns.keys():
                if field_name in ['uuid', 'content', 'datatype']:
                    continue
                if field_name in additional_fields:
                    field_names.append(field_name)
                    field_values.append(additional_fields[field_name])
        
        # Prepare the SQL statement
        placeholders = ','.join(['?' for _ in field_names])
        field_list = ','.join(field_names)
        
        # Insert or update the record
        sql = f'''INSERT OR REPLACE INTO {table_name}
                 ({field_list})
                 VALUES ({placeholders})'''
        
        cursor.execute(sql, field_values)
        conn.commit()
        return identifier
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving to database: {str(e)}")
        raise e


def get_from_db(conn: sqlite3.Connection, table_name: str, identifier: str) -> Any:
    """
    Retrieve content from the database and restore its original Python data type.
    
    Args:
        conn: SQLite connection object
        table_name: Name of the table containing the content
        identifier: UUID of the record to retrieve
    
    Returns:
        The content in its original Python data type
        
    Raises:
        ValueError: If the record is not found
    """
    cursor = conn.cursor()
    
    try:
        cursor.execute(f'''SELECT content, datatype 
                         FROM {table_name}
                         WHERE uuid = ?''', (identifier,))
        
        result = cursor.fetchone()
        if result is None:
            raise ValueError(f"No record found with UUID: {identifier}")
            
        serialized_content, datatype = result
        
        # Deserialize the content
        content = pickle.loads(serialized_content)
        
        # Verify the deserialized content matches the stored type
        if type(content).__name__ != datatype:
            raise ValueError(f"Type mismatch: stored type was {datatype} but deserialized as {type(content).__name__}")
            
        return content
            
    except Exception as e:
        raise e

# Example usage:
"""
import sqlite3

# Open database connection
conn = sqlite3.connect('data.db')

try:
    # First, create a table with additional fields
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS my_table
                     (uuid TEXT PRIMARY KEY,
                      content BLOB NOT NULL,
                      datatype TEXT NOT NULL,
                      category TEXT,
                      timestamp TEXT,
                      status INTEGER)''')
    
    # Prepare some data
    list_data = [1, 2, 3, 4, 5]
    additional_info = {
        'category': 'numbers',
        'timestamp': '2025-02-01 12:00:00',
        'status': 1
    }
    
    # Save data with additional fields
    list_id = save_to_db(conn, "my_table", list_data, 
                        additional_fields=additional_info)
    
    # Retrieve the data
    retrieved_list = get_from_db(conn, "my_table", list_id)
    print(f"Retrieved list: {retrieved_list}")
    
    # View all data in the record
    cursor.execute('SELECT * FROM my_table WHERE uuid = ?', (list_id,))
    full_record = cursor.fetchone()
    print(f"Full record: {full_record}")
    
finally:
    conn.close()
"""

def update_record_from_dict(conn: sqlite3.Connection, table_name: str, identifier: str, update_dict: Dict) -> bool:
    """
    Update a record in the database with new values from a dictionary.
    Only non-BLOB fields will be updated.
    Only updates fields that are present in both the update_dict and the table.
    Will ignore any fields in the update_dict that are not in the table
    
    Args:
        conn: SQLite connection object
        table_name: Name of the table containing the record
        identifier: UUID of the record to update
        update_dict: Dictionary of field names and new values to update
    
    Returns:
        bool: True if the record was updated successfully, False otherwise
    """
    cursor = conn.cursor()
    
    try:
        # Get table structure
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        # Filter out BLOB columns and build column list
        non_blob_columns = [col[1] for col in columns if col[2].upper() != 'BLOB']
        
        # Filter update_dict to only include keys that are in non_blob_columns
        filtered_update_dict = {key: value for key, value in update_dict.items() if key in non_blob_columns}
        
        # Log ignored keys
        ignored_keys = set(update_dict.keys()) - set(filtered_update_dict.keys())
        for key in ignored_keys:
            logger.debug(f"Ignored key not found in table '{table_name}': {key}")
        
        # Prepare the SQL statement
        set_values = ','.join([f"{col} = ?" for col in filtered_update_dict.keys()])
        
        # Update the record
        cursor.execute(f'''UPDATE {table_name}
                         SET {set_values}
                         WHERE uuid = ?''', 
                       tuple(filtered_update_dict[col] for col in filtered_update_dict.keys()) + (identifier,))
        
        conn.commit()
        return True
            
    except Exception as e:
        conn.rollback()
        raise e


def get_record_metadata(conn: sqlite3.Connection, table_name: str, identifier: str) -> Dict:
    """
    Retrieve all non-BLOB fields from a record as a dictionary.
    
    Args:
        conn: SQLite connection object
        table_name: Name of the table containing the record
        identifier: UUID of the record to retrieve
    
    Returns:
        Dict containing all non-BLOB field names and values
        
    Raises:
        ValueError: If the record is not found
    """
    cursor = conn.cursor()
    
    try:
        # Get table structure
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        # Filter out BLOB columns and build column list
        non_blob_columns = [col[1] for col in columns if col[2].upper() != 'BLOB']
        column_list = ','.join(non_blob_columns)
        
        # Query the record
        cursor.execute(f'''SELECT {column_list}
                         FROM {table_name}
                         WHERE uuid = ?''', (identifier,))
        
        result = cursor.fetchone()
        if result is None:
            raise ValueError(f"No record found with UUID: {identifier}")
        
        # Create dictionary from results
        return dict(zip(non_blob_columns, result))
            
    except Exception as e:
        raise e


def store_blob_to_db(conn: sqlite3.Connection, identifier: str, blob: Any, attributes: dict) -> bool:
    """
    Store a binary large object (BLOB) in the database.
    If the UUID exists, update the record. Otherwise, insert a new one.
    """
    cursor = conn.cursor()
    # ok_to_store = False
    datatype = None

    if isinstance(blob, (bytes)):
        # ok_to_store = True
        datatype = 'bytes'
    elif isinstance(blob, (bytearray)):
        # ok_to_store = True
        datatype = 'bytearray'
    elif isinstance(blob, str):
        blob = blob.encode('utf-8')
        # ok_to_store = True
        datatype = 'str'
    elif isinstance(blob, list):
        blob = pickle.dumps(blob)
        # ok_to_store = True
        datatype = 'list'
    elif isinstance(blob, dict):
        blob = pickle.dumps(blob)
        # ok_to_store = True
        datatype = 'dict'
    elif blob is None:
        blob = None
        # ok_to_store = True
        datatype = 'NoneType'
    else:
        raise ValueError(f"Unsupported data type: {type(blob)}")
    
    compress = attributes.get('compress', False)
    acquired = attributes.get('acquired', convert_datetime_format())
    filename = attributes.get('filename', "")
    original_location = attributes.get('original_location', "")
    file_type = attributes.get('file_type', "")
    mime_type = attributes.get('mime_type', "")
    try:
        if compress and blob is not None:
            logger.debug("Compressing blob data")
            blob = zlib.compress(blob)
            compressed = 1  # True as integer
        else:
            compressed = 0  # False as integer

        # Check if table exists
        cursor.execute(f"PRAGMA table_info({FILE_CACHE_TABLE})")
        table_columns = {row[1]: row[2] for row in cursor.fetchall()}
        if not table_columns:
            logger.error(f"Table '{FILE_CACHE_TABLE}' does not exist in the database")
            return False

        # Check if the record exists
        cursor.execute(f"SELECT 1 FROM {FILE_CACHE_TABLE} WHERE uuid = ?", (identifier,))
        exists = cursor.fetchone() is not None

        if exists:
            logger.debug(f"Updating existing BLOB record in '{FILE_CACHE_TABLE}' with identifier '{identifier}'")
            query = f"""UPDATE {FILE_CACHE_TABLE}
                        SET content = ?, datatype = ?, compressed = ?, acquired = ?, filename = ?, original_location = ?, file_type = ?, mime_type = ?
                        WHERE uuid = ?"""
            params = (blob, datatype, compressed, acquired, filename, original_location, file_type, mime_type, identifier)
        else:
            logger.debug(f"Inserting new BLOB record in '{FILE_CACHE_TABLE}' with identifier '{identifier}'")
            query = f"""INSERT INTO {FILE_CACHE_TABLE} 
                        (uuid, content, datatype, compressed, acquired, filename, original_location, file_type, mime_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            params = (identifier, blob, datatype, compressed, acquired, filename, original_location, file_type, mime_type)

        cursor.execute(query, params)
        logger.debug(f"Query: {query}")
        logger.debug(f"Parameters: blob_size={len(blob) if blob else 'None'}, datatype={datatype}, compressed={compressed}, uuid={identifier}")
        
        conn.commit()
        return True
            
    except Exception as e:
        conn.rollback()
        raise e

def retrieve_blob_from_db(conn: sqlite3.Connection, identifier: str) -> Any:
    """
    Retrieve a binary large object (BLOB) from the database.
    
    Args:
        conn: SQLite connection object
        table_name: Name of the table containing the record
        identifier: UUID of the record to retrieve the BLOB from
        decompress: Whether to decompress the BLOB after retrieval
    
    Returns:
        The BLOB data, or None if not found
    """
    cursor = conn.cursor()
    return_dict = {}
    
    try:
        cursor.execute(f'''SELECT * 
                         FROM {FILE_CACHE_TABLE}
                         WHERE uuid = ?''', (identifier,))
        
        result = cursor.fetchone()
        # logger.debug(f"Result '{result}'")
        
        if result is not None:
            # Unpack the result
            return_dict = {
            "uuid": result[0],
            "filename": result[1],
            "original_location": result[2],
            "mime_type": result[3],
            "file_type": result[4],
            "acquired": result[5],
            "datatype": result[6],
            "compressed": result[7],
            "content": result[8]
            }
            # logger.debug(f"Retrieved BLOB data for identifier '{identifier}'")
            
            if return_dict["compressed"] == 1:
                return_dict["content"] = zlib.decompress(return_dict["content"])
            else:
                return_dict["content"] = return_dict["content"]

            if return_dict["datatype"] == 'bytes':
                return_dict["content"] = bytes(return_dict["content"])
            elif return_dict["datatype"] == 'str':
                return_dict["content"] = return_dict["content"].decode('utf-8')
            elif return_dict["datatype"] == 'list':
                return_dict["content"] = pickle.loads(return_dict["content"])
            elif return_dict["datatype"] == 'dict':
                return_dict["content"] = pickle.loads(return_dict["content"])
            elif return_dict["datatype"] == 'NoneType':
                return_dict["content"] = None
            elif return_dict["datatype"] == 'bytearray':
                return_dict["content"] = bytearray(return_dict["content"])
            else:
                raise ValueError(f"Unexpected data type: {return_dict['datatype']}")
        else :
            raise ValueError(f"No record found with UUID: {identifier}")

        return return_dict
            
    except Exception as e:
        raise e
    
# -----------------------------------------------------------------------------
def open_sqlite3(target: str) -> Optional[sqlite3.Connection]:
    """
    Opens a SQLite3 database file.
    SQLite3 will automatically create the database if it does not exist.
    Includes copilot-suggested error handling.
    """
    status = False
    conn = None
    logger.debug(f"Opening {target}")
    try:
        # Ensure the directory exists
        db_dir = os.path.dirname(target)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(target, check_same_thread=False)
        status = True
        logger.debug(f"database opened: {target}")
    except sqlite3.IntegrityError:
        logger.error("Integrity Error: This violates the database's integrity rules.")
    except sqlite3.ProgrammingError as pe:
        logger.error(f"Programming Error: {pe}")
    except sqlite3.OperationalError as oe:
        logger.error(f"Operational Error: {oe}")
        if not os.path.exists(os.path.dirname(target)):
            logger.error(f"Directory does not exist: {os.path.dirname(target)}")
        elif not os.access(os.path.dirname(target), os.W_OK):
            logger.error(f"No write permission to directory: {os.path.dirname(target)}")
    except sqlite3.DatabaseError as de:
        logger.error(f"Database Error: {de}")
    except sqlite3.InterfaceError as ie:
        logger.error(f"Interface Error: {ie}")
    except Exception as error:
        logger.error(f"Unrecognized error opening {target} ({type(error).__name__}): {str(error)}")

    if not status:
        conn = None
    return conn

# =============================================================================
#  --- MAIN: Only runs if the module is executed stand-alone. ---
# =============================================================================
if __name__ == '__main__':
    example_usage = """
    import sqlite3

    conn = sqlite3.connect('data.db')

    try:
        # First create a record with some metadata
        content = ["example", "data"]
        additional_fields = {
            'category': 'test',
            'created_by': 'user123',
            'status': 1,
            'notes': 'Sample record'
        }
        
        # Save the record
        record_id = save_to_db(conn, "my_table", content, 
                            additional_fields=additional_fields)
        
        # Retrieve the metadata
        metadata = get_record_metadata(conn, "my_table", record_id)
        print("Record metadata:", metadata)
        # Output might look like:
        # {
        #     'uuid': '123e4567-e89b-12d3-a456-426614174000',
        #     'datatype': 'list',
        #     'category': 'test',
        #     'created_by': 'user123',
        #     'status': 1,
        #     'notes': 'Sample record'
        # }
        
    finally:
        conn.close()
    """
    print("SQLite3 Functions. Not intended to be run as a stand-alone file.")
    print("Example usage:")
    print(example_usage)
