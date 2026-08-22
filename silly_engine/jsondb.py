#! /usr/bin/env python3

"""
Version:
- 1.2.1: better migration system, with version comparison and migration applicability check:
- 1.2.0: support for atomic file writes and crash-safe saving, plus minor bugfixes
- 1.1.2: bugfix in _id attribution in Collection.insert() and Collection.update()
- 1.1.1: support custom dataclass for input/output
- 1.0.0
Use a json file as a database, read the docstrings to know more.

e.g.:
from JsonDb import JsonDb

db = JsonDb(
    "data.json",
    autosave=True
    )

Truc = db.collection("Truc")
Machin = db.collection("Machin")

object1 = Truc.insert({"name": "machin", "age": 12})
object2 = Truc.insert({"name": "bidule", "age": 18})

key = object1["_id"]

print(Truc.get(key))

"""
from __future__ import annotations
from pathlib import Path
from dataclasses import is_dataclass, asdict

import json
import os
import uuid

from typing import Any, Callable, Generic, Sequence, Type, TypeVar

VERSION = "1.2.1"

WIDTH=80

OutputModel = TypeVar('OutputModel')

class JsonDbError(Exception):
    pass


def version_tuple(version_str: str) -> tuple[int, ...]:
    """Convert a version string like '1.2.3' to a tuple (1, 2, 3) for comparison."""
    try:
        return tuple(int(part) for part in version_str.split('.'))
    except ValueError:
        raise JsonDbError(f"Invalid version format: '{version_str}'. Expected format is 'X.Y.Z' where X, Y, Z are integers.")

class Item:
    def __init__(self, data: dict | Any, collection: Collection, _id=None) -> None:
        # Priority is explicit _id parameter, then data['_id'], then a new UUID.
        if _id is not None:
            self._id = _id
        elif isinstance(data, dict) and data.get("_id") is not None:
            self._id = data["_id"]
        else:
            self._id = str(uuid.uuid4())
        self.collection = collection
        self.data = data
        self.data['_id'] = self._id

    def __repr__(self) -> str:
        return f"<Item - {self.data}>"

    def _autosave(self) -> None:
        if self.collection.database.is_autosaving:
            self.collection.database.save()

    def set(self, *args: tuple) -> Any:
        """args are tuples of (key, value)"""
        try:
            for arg in args:
                if not isinstance(arg, tuple):
                    raise JsonDbError('expected argument type is tuple')
                self.data[arg[0]] = arg[1]
        except JsonDbError as error:
            raise error
        self._autosave()
        return self

    def del_attr(self, *args: str) -> Any:
        for arg in args:
            if not type(arg) is str:
                raise JsonDbError('expected argument type is str')
            if arg in self.data:
                del self.data[arg]
        self._autosave()
        return self

    def update(self, data) -> Any:
        for key in data:
            self.data[key] = data[key]
        self._autosave()
        return self

    def delete(self) -> Item:
        item = self
        del self.collection.data[self._id]
        self._autosave()
        return item

    def to_dict(self) -> dict:
        return self.data


class JsonDb:
    """Interface with a json file"""

    def __init__(
            self, file: str | Path="db.json", autosave: bool=False,
            version: str="0.0.0", migrations: dict[str, Callable] | None=None,
            width: int=WIDTH
            ) -> None:
        self.is_autosaving = autosave
        self.file = file
        self.collections = {}
        self.width = width
        self._version = version
        self._migrations = migrations

        if os.path.exists(self.file):
            self.load()

        # check _settings and version
        settings = self.collection("_settings")
        recorded_settings = settings.first()
        if recorded_settings is None:
            settings = self.collection("_settings")
            settings.first_update({"version": self._version, "description": "Singleton JsonDb Configuration"})
            self.save()
        elif recorded_settings.data.get("version", None) is None:
            settings.first_update({"version": self._version})

        # migrations
        recorded_settings = settings.first()
        assert recorded_settings is not None
        recorded_version = recorded_settings.data.get("version", "0.0.0")
        assert recorded_version is not None
        if self._migrations is not None:
            for migration in self._migrations:
                if version_tuple(recorded_version) < version_tuple(migration) <= version_tuple(self._version):
                    print(f"Migration to v{migration}...")
                    self._migrations[migration](self)
                    print(f"Successfully upgraded JsonDb to v{self._version}")
        if recorded_version != self._version:
            settings.first_update({"version": self._version})



    def __repr__(self) -> str:
        collection_count = len(self.collections)
        return f"<JsonDb({self.file}, v{self._version}) collections: {collection_count} >"

    def _autosave(self) -> None:
        """Save the database if autosave is enabled"""
        if self.is_autosaving:
            self.save()

    def _ensure_dir(self, path) -> None:
        if path:
            os.makedirs(path, exist_ok=True)

    def collection(self, name: str, model: Type[OutputModel] | None=None) -> Collection:
        if name not in self.collections:
            self.collections[name] = Collection(name, self, model=model)
            self._autosave()
            return self.collections[name]
        else:
            collection = self.collections[name]
            if model is not None:
                collection.model = model
            return collection

    def save(self) -> None:
        if self.file is None:
            return
        target_path = str(self.file)
        dirpath = os.path.dirname(target_path)
        self._ensure_dir(dirpath)
        data = {}
        for collection in self.collections:
            data[collection] = {}
            for id in self.collections[collection].data:
                data[collection][id] = self.collections[collection].data[id].data
        try:
            json_str = json.dumps(data, indent=2)
        except (TypeError, ValueError) as e:
            raise JsonDbError(e)

        temp_path = f"{target_path}.{os.getpid()}.{uuid.uuid4().hex}.jsondb-write-tmp"
        try:
            with open(temp_path, 'w', encoding='utf-8') as file:
                file.write(json_str)
                file.flush()
                os.fsync(file.fileno())

            # Atomic replace on the same filesystem.
            os.replace(temp_path, target_path)
        except OSError as e:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass
            raise JsonDbError(e)

    def load(self) -> None:
        if self.file is None:
            return
        previous_autosave = self.is_autosaving
        self.is_autosaving = False

        if os.path.exists(self.file):
            try:
                with open(self.file, 'r') as file:
                    data = json.load(file)
            except json.JSONDecodeError:
                self.is_autosaving = previous_autosave
                raise JsonDbError(f"The JsonDb file {self.file} exists but seems to be corrupted.")

            for collection_name in data:
                new_collection = self.collection(collection_name)
                for id in data[collection_name]:
                    new_collection.insert(data[collection_name][id], id)

        self.is_autosaving = previous_autosave

        dirpath = os.path.dirname(str(self.file))
        self._ensure_dir(dirpath)

    def show(self) -> str:
        width = self.width
        collections_count = len(self.collections)
        display = '\n+'+'-'*(width-2) + "+\n"
        display += f"|*-- JsonDb --* file: {self.file} - collections: {collections_count:<13}\n"
        display += f"| {'Collections':40} | {'Item(s)':10}\n"
        display += '+'+'-'*(width-2) + "+\n"

        for collection in self.collections:
            item_count = len(self.collections[collection].data)
            display += f"| {collection:40} | {item_count:10}\n"
        display += '+'+'-'*(width-2) + "+\n"
        return display

    def drop(self, collection_name: str | Collection) -> None:
        """Delete a collection and all its items"""
        if isinstance(collection_name, Collection):
            collection_name = collection_name.name
        if collection_name in self.collections:
            del self.collections[collection_name]
            self._autosave()


class Collection(Generic[OutputModel]):
    """Collection of dictionnary objects"""
    def __init__(self, name: str, db: JsonDb, model: Type[OutputModel] | None=None) -> None:
        self.database = db
        self.name = name
        self.data = {}
        self.model = model

        if not is_dataclass(model) and model is not None:
            raise JsonDbError("The model must be a dataclass")


    def __repr__(self) -> str:
        return f"<{self.name} - objects in collection: {len(self.database.collection(self.name).data)}>"

    def _autosave(self) -> None:
        if self.database.is_autosaving:
            self.database.save()

    def _output_model_format(self, item: Item) -> Item | OutputModel:
        """Format the output data with the model if it exists, return a dict if the formatting fails"""
        if self.model is None:
            return item
        try:
            return self.model(**item.data)
        except Exception as e:
            raise JsonDbError(f"Output formatting error for collection '{self.name}': {e}")

    def insert(self, input_data: dict | Any | OutputModel, _id=None) -> Item | OutputModel:
        """Add an item to the collection.

        ID resolution order:
        1. Use explicit `_id` argument when provided (used by `load()` to restore keys).
        2. Otherwise, preserve `_id` present in `input_data` when available.
        3. Otherwise, let `Item` generate a new UUID.
        """
        if is_dataclass(input_data) and not isinstance(input_data, type):
            input_data = asdict(input_data)

        item = Item(input_data, self, _id=_id)
        self.data[item._id] = item
        self._autosave()
        return self._output_model_format(item)

    def update(self, input_data: dict | Any | OutputModel, _id=None) -> Item | OutputModel:
        """Update an item in the collection"""
        if is_dataclass(input_data) and not isinstance(input_data, type):
            input_data = asdict(input_data)
        try:
            assert isinstance(input_data, dict), "Input data must be a dict or a dataclass instance"
        except AssertionError as e:
            raise JsonDbError(e)
        if input_data.get("_id") is None:
            if _id is None:
                raise JsonDbError("The item must have an '_id' key")
            else:
                input_data["_id"] = _id
        item = Item(input_data, self, _id=input_data["_id"])
        self.data[item._id] = item
        self._autosave()
        return self._output_model_format(item)

    def delete(self, input_data: dict | Item | OutputModel | str, _id=None) -> str:
        """Delete an item from the collection
        e.g: self.delete({"_id": "item_id"} | item_instance | "item_id")
        """
        if _id is None:
            if isinstance(input_data, Item):
                _id = input_data._id
            elif isinstance(input_data, dict) and input_data.get("_id") is not None:
                _id = input_data["_id"]
            elif isinstance(input_data, str):
                _id = input_data
            elif is_dataclass(input_data) and not isinstance(input_data, type):
                input_dict = asdict(input_data)
                if input_dict.get("_id") is not None:
                    _id = input_dict["_id"]
                else:
                    raise JsonDbError("The item must have an '_id' key")
            else:
                raise JsonDbError("The item must have an '_id' key")
        del self.data[_id]
        self._autosave()
        return _id

    def all(self) -> Sequence[Item | OutputModel]:
        """Returns all the items of the collection"""
        return self.filter(lambda x: True)

    def show(self) -> str:
        """Fancy representation of the collection and its items
        e.g.: print(Collection.show())
        """
        width = self.database.width
        display = '\n+'+'-'*(width-2) + "+\n"
        display += f"|*-- Collection: {self.name} --*\n"
        for _id in self.data:
            display += f"| {_id} \n"
        display += f"| Total items: {len(self.data)}\n"
        display += '+'+'-'*(width-2) + "+\n"
        return display

    def first(self) -> None | Item | OutputModel:
        """
        For singletons collections,
        Returns the first item of the collection or None if the collection is empty
        """
        if len(self.data) == 0:
            return None
        for key in self.data:
            return self._output_model_format(self.data[key])


    def first_update(self, input_data: dict | Item | OutputModel) -> Item | OutputModel | None:
        """
        For singletons collections, update the firts item
        """
        if is_dataclass(input_data) and not isinstance(input_data, type):
            input_data = asdict(input_data)
        if len(self.data) == 0:
            new_data = self.insert(input_data)
            return new_data
        for key in self.data:
            new_item = Item(input_data, self, _id=key)
            self.data[key] = new_item
            self._autosave()
            # only the first item, so return here:
            return self._output_model_format(new_item)


    def get(self, key: str) -> Item | OutputModel | None:
        """Get a unique item dict from its id"""
        if key in self.data:
            return self._output_model_format(self.data[key])


    def filter(self, query_func: Callable) -> Sequence[Item | OutputModel]:
        """Takes one parameter function that returns a boolean value
        example: queryset = Collection.filter(lambda x: x['age'] > 18)

        returns a list of datas.
        """
        queryset = []
        for _id in self.data:
            try:
                if query_func(self.data[_id].data):
                    queryset.append(self._output_model_format(self.data[_id]))
            except KeyError:
                continue
        return queryset


    def filter_delete(self, query_func: Callable) -> list[str]:
        """Takes one parameter function that returns a boolean value
        example: Collection.query_delete(lambda x: x['age'] > 18)
        """
        to_delete = []
        for _id in self.data:
            item = self.data[_id]
            try:
                if query_func(item.data):
                    to_delete.append(item._id)
            except KeyError:
                continue
        for item_id in to_delete:
            self.data[item_id].delete()
        self._autosave()
        return to_delete
