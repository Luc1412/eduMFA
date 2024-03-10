# -*- coding: utf-8 -*-
#
# License:  AGPLv3
# This file is part of eduMFA. eduMFA is a fork of privacyIDEA which was forked from LinOTP.
# Copyright (c) 2024 eduMFA Project-Team
# Previous authors by privacyIDEA project:
#
# 2014 - 2015 Cornelius Kölbel <cornelius@privacyidea.org>
#
# Copyright (C) 2010 - 2014 LSE Leading Security Experts GmbH
# License:  AGPLv3
# contact:  http://www.linotp.org
#           http://www.lsexperts.de
#           linotp@lsexperts.de
#
# This code is free software; you can redistribute it and/or
# modify it under the terms of the GNU AFFERO GENERAL PUBLIC LICENSE
# License as published by the Free Software Foundation; either
# version 3 of the License, or any later version.
#
# This code is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU AFFERO GENERAL PUBLIC LICENSE for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
__doc__ = """There are the library functions for user functions.
It depends on the lib.resolver and lib.realm.

There are and must be no dependencies to the token functions (lib.token)
or to webservices!

This code is tested in tests/test_lib_user.py
"""

import logging
import traceback

from .error import UserError
from ..api.lib.utils import getParam, optional
from .log import log_with
from .resolver import get_resolver_object, get_resolver_type

from .realm import (
    get_realms,
    realm_is_defined,
    get_default_realm,
    get_realm,
    get_realm_id,
)
from .config import get_from_config, SYSCONF
from .usercache import user_cache, cache_username, user_init, delete_user_cache
from edumfa.models import CustomUserAttribute, db

log = logging.getLogger(__name__)


class User(object):
    """
    The user has the attributes
      login, realm and resolver.
    Usually a user can be found via "login@realm".

    A user object with an empty login and realm should not exist,
    whereas a user object could have an empty resolver.
    """

    # In some test case the login attribute from a not
    # initialized user is requested. This is why we need
    # these dummy class attributes.
    login = ""
    realm = ""
    resolver = ""

    # NOTE: Directly decorating the class ``User`` breaks ``isinstance`` checks,
    # which is why we have to decorate __init__
    @log_with(log)
    def __init__(self, login="", realm="", resolver="", uid=None):
        self.login = login or ""
        self.used_login = self.login
        self.realm = (realm or "").lower()
        self.realm_id = None
        if resolver == "**":
            resolver = ""
        self.resolver = resolver or ""
        self.uid = uid
        self.rtype = None
        if not self.login and not self.resolver and uid is not None:
            raise UserError("Can not create a user object from a uid without a resolver!")
        # Enrich user object with information from the userstore or from the
        # usercache
        if login or uid is not None:
            self._get_user_from_userstore()
            # Just store the resolver type
            self.rtype = get_resolver_type(self.resolver)
            # Add realm_id to User object
            self.realm_id = get_realm_id(self.realm)

    @user_cache(user_init)
    def _get_user_from_userstore(self):
        if not self.resolver:
            # set the resolver implicitly!
            self._get_resolvers()

        # Get Identifiers
        if self.resolver:
            y = get_resolver_object(self.resolver)
            if y is None:
                raise UserError(f"The resolver '{self.resolver!s}' does not exist!")
            if self.uid is None:
                # Determine the uid
                self.uid = y.getUserId(self.login)
            if not self.login:
                # Determine the login if it does not exist or
                self.used_login = self.login = y.getUsername(self.uid)
            if y.has_multiple_loginnames:
                # if the resolver has multiple logins the primary login might be another value!
                self.login = y.getUsername(self.uid)

    def is_empty(self):
        # ignore if only resolver is set! as it makes no sense
        if len(self.login or "") + len(self.realm or "") == 0:
            return True
        else:
            return False

    def __eq__(self, other):
        """
        Compare two User Objects.

        :param other: The other User object, to which this very object is
        compared.
        :type other: User object
        :return: True or False
        :rtype: bool
        """
        if not isinstance(other, type(self)):
            log.info(f"Comparing a non-user object: {self!s} != {type(other)!s}.")
            return False
        if (self.resolver != other.resolver) or (self.realm != other.realm):
            log.info(f"Users are not in the same resolver and realm: {self!s} != {other!s}.")
            return False
        if self.uid and other.uid:
            log.debug(f"Comparing based on uid: {self.uid!s} vs {other.uid!s}")
            return self.uid == other.uid
        log.debug(f"Comparing based on login: {self.login!s} vs {other.login!s}")
        return self.login == other.login

    def __ne__(self, other):
        """
        Compare two user objects and return true, if they are not equal

        :param other: The other User objkect
        :return: True or False
        """
        return not self.__eq__(other)

    def __hash__(self):
        return hash((type(self), self.login, self.resolver, self.realm))

    def __str__(self):
        ret = "<empty user>"
        if not self.is_empty():
            # Realm and resolver should always be ASCII
            conf = ""
            if self.resolver:
                conf = f".{self.resolver!s}"
            ret = f"<{self.login!s}{conf!s}@{self.realm!s}>"
        return ret

    def __repr__(self):
        ret = f"User(login={self.login!r}, realm={self.realm!r}, resolver={self.resolver!r})"
        return ret

    def __bool__(self):
        return not self.is_empty()

    __nonzero__ = __bool__

    @log_with(log)
    def get_ordererd_resolvers(self):
        """
        returns a list of resolvernames ordered by priority.
        The resolver with the lowest priority is the first.
        If resolvers have the same priority, they are ordered alphabetically.

        :return: list or resolvernames
        """
        resolver_tuples = []
        realm_config = get_realms(self.realm)
        resolvers_in_realm = realm_config.get(self.realm, {}).get("resolver", {})
        for resolver in resolvers_in_realm:
            # append a tuple
            resolver_tuples.append((resolver.get("name"), resolver.get("priority") or 1000))

        # sort the resolvers by the 2nd entry in the tuple, the priority
        resolvers = sorted(resolver_tuples, key=lambda resolver: resolver[1])
        resolvers = [r[0] for r in resolvers]
        return resolvers

    def _get_resolvers(self, all_resolvers=False):
        """
        This returns the list of the resolvernames of the user.
        If no resolver attribute exists at the moment, the user is searched
        in the realm and according to this the resolver attribute is set.

        It will only return one resolver in the list for backward compatibility

        .. note:: If the user does not exist in the realm, then an empty
           list is returned!

        :param all_resolvers: return all resolvers (of a realm), in which
            the user is contained
        :return: list of resolvers for self.login
        :rtype: list of strings
        """
        if self.resolver:
            return [self.resolver]

        resolvers = []
        for resolvername in self.get_ordererd_resolvers():
            # test, if the user is contained in this resolver
            if self._locate_user_in_resolver(resolvername):
                break
        if self.resolver:
            resolvers = [self.resolver]
        return resolvers

    def _locate_user_in_resolver(self, resolvername):
        """
        Try to locate the user (by self.login) in the resolver with the given name.
        In case of success, this sets `self.resolver` as well as `self.uid`
        and returns True. If the resolver does not exist or the user does
        not exist in the resolver, False is returned.
        :param resolvername: string denoting the resolver name
        :return: boolean
        """
        y = get_resolver_object(resolvername)
        if y is None:  # pragma: no cover
            log.info(f"Resolver {resolvername!r} not found!")
            return False
        else:
            uid = y.getUserId(self.login)
            if uid not in ["", None]:
                log.info(f"user {self.login!r} found in resolver {resolvername!r}")
                log.info(f"userid resolved to {uid!r} ")
                self.resolver = resolvername
                self.uid = uid
                # We do not need to search other resolvers!
                return True
            else:
                log.debug(f"user {self.login!r} not found in resolver {resolvername!r}")
                return False

    def get_user_identifiers(self):
        """
        This returns the UserId  information from the resolver object and
        the resolvertype and the resolvername
        (former: getUserId)
        (former: getUserResolverId)
        :return: The userid, the resolver type and the resolver name
                 like (1000, "passwdresolver", "resolver1")
        :rtype: tuple
        """
        if not self.resolver:
            raise UserError("The user can not be found in any resolver in this realm!")
        return self.uid, self.rtype, self.resolver

    def exist(self):
        """
        Check if the user object exists in the user store
        :return: True or False
        """
        return bool(self.uid)

    @property
    def info(self):
        """
        return the detailed information for the user

        :return: a dict with all the userinformation
        :rtype: dict
        """
        if self.is_empty():
            # An empty user has no info
            return {}
        (uid, _rtype, _resolver) = self.get_user_identifiers()
        if uid == None:
            return {}
        y = get_resolver_object(self.resolver)
        userInfo = y.getUserInfo(uid)
        # Now add the custom attributes, this is used e.g. in ADDUSERINRESPONSE
        userInfo.update(self.attributes)
        return userInfo

    @log_with(log)
    def set_attribute(self, attrkey, attrvalue, attrtype=None):
        """
        Set a custom attribute for a user

        :param attrkey: The key of the attribute
        :param attrvalue: The value of the attribute
        :return: The id of the attribute setting
        """
        ua = CustomUserAttribute(
            user_id=self.uid,
            resolver=self.resolver,
            realm_id=self.realm_id,
            Key=attrkey,
            Value=attrvalue,
            Type=attrtype,
        ).save()
        return ua

    @property
    def attributes(self):
        """
        returns the custom attributes of a user
        :return: a dictionary of attributes with keys and values
        """
        return get_attributes(self.uid, self.resolver, self.realm_id)

    @log_with(log)
    def delete_attribute(self, attrkey=None):
        """
        Delete the given key as custom user attribute.
        If no key is given, then all attributes are deleted

        :param attrkey: The key to delete
        :return: The number of deleted rows
        """
        if attrkey:
            ua = CustomUserAttribute.query.filter_by(
                user_id=self.uid,
                resolver=self.resolver,
                realm_id=self.realm_id,
                Key=attrkey,
            ).delete()
        else:
            ua = CustomUserAttribute.query.filter_by(user_id=self.uid, resolver=self.resolver, realm_id=self.realm_id).delete()
        db.session.commit()
        return ua

    @log_with(log)
    def get_user_phone(self, phone_type="phone", index=None):
        """
        Returns the phone number or a list of phone numbers of a user.

        :param phone_type: The type of the phone, i.e. either mobile or
                           phone (land line)
        :type phone_type: string
        :param index: The index of the selected phone number of list of the phones of the user.
            If the index is given, this phone number as string is returned.
            If the index is omitted, all phone numbers are returned.

        :returns: list with phone numbers of this user object
        """
        userinfo = self.info
        if phone_type in userinfo:
            phone = userinfo[phone_type]
            log.debug(f"got user phone {phone!r} of type {phone_type!r}")
            if type(phone) == list and index is not None:
                if len(phone) > index:
                    return phone[index]
                else:
                    log.warning(f"userobject ({self!r}) has not that much phone numbers ({index!r} of {phone!r}).")
                    return ""
            else:
                return phone
        else:
            log.warning(f"userobject ({self!r}) has no phone of type {phone_type!r}.")
            return ""

    @log_with(log)
    def get_user_realms(self):
        """
        Returns a list of the realms, a user belongs to.
        Usually this will only be one realm.
        But if the user object has no realm but only a resolver,
        than all realms, containing this resolver are returned.
        This function is used for the policy module

        :return: realms of the user
        :rtype: list
        """
        allRealms = get_realms()
        Realms = []
        if self.realm == "" and self.resolver == "":
            defRealm = get_default_realm().lower()
            Realms.append(defRealm)
            self.realm = defRealm
        elif self.realm != "":
            Realms.append(self.realm.lower())
        else:
            # User has no realm!
            # we have got a resolver and will get all realms
            # the resolver belongs to.
            for key, val in allRealms.items():
                log.debug(f"evaluating realm {key!r}: {val!r} ")
                for reso in val.get("resolver", []):
                    resoname = reso.get("name")
                    if resoname == self.resolver:
                        Realms.append(key.lower())
                        log.debug(f"added realm {key!r} to Realms due to resolver {self.resolver!r}")
        return Realms

    @log_with(log, log_entry=False)
    def check_password(self, password):
        """
        The password of the user is checked against the user source

        :param password: The clear text password
        :return: the username of the authenticated user.
                 If unsuccessful, returns None
        :rtype: string/None
        """
        success = None
        try:
            log.info(f"User {self.login!r} from realm {self.realm!r} tries to authenticate")
            res = self._get_resolvers()
            # Now we know, the resolvers of this user and we can verify the
            # password
            if len(res) == 1:
                y = get_resolver_object(self.resolver)
                uid, _rtype, _rname = self.get_user_identifiers()
                if y.checkPass(uid, password):
                    success = f"{self.login!s}@{self.realm!s}"
                    log.debug(f"Successfully authenticated user {self!r}.")
                else:
                    log.info(f"user {self!r} failed to authenticate.")

            elif not res:
                log.error(f"The user {self!r} exists in NO resolver.")
        except UserError as e:  # pragma: no cover
            log.error(f"Error while trying to verify the username: {e!r}")
        except Exception as e:  # pragma: no cover
            log.error(f"Error checking password within module {e!r}")
            log.debug(f"{traceback.format_exc()!s}")

        return success

    @log_with(log)
    def get_search_fields(self):
        """
        Return the valid search fields of a user.
        The search fields are defined in the UserIdResolver class.

        :return: searchFields with name (key) and type (value)
        :rtype: dict
        """
        searchFields = {}

        for reso in self._get_resolvers():
            # try to load the UserIdResolver Class
            try:
                y = get_resolver_object(reso)
                sf = y.getSearchFields()
                searchFields[reso] = sf

            except Exception as e:  # pragma: no cover
                log.warning(f"module {reso!r}: {e!r}")

        return searchFields

    # If passwords should not be logged, we hide it from the log entry
    @log_with(log, hide_kwargs=["password"])
    def update_user_info(self, attributes, password=None):
        """
        This updates the given attributes of a user.
        The attributes can be "username", "surname", "givenname", "email",
        "mobile", "phone", "password"

        :param attributes: A dictionary of the attributes to be updated
        :type attributes: dict
        :param password: The password of the user
        :return: True in case of success
        """
        if password is not None:
            attributes["password"] = password
        success = False
        try:
            log.info(f"User info for user {self.login!r}@{self.realm!r} about to be updated.")
            res = self._get_resolvers()
            # Now we know, the resolvers of this user and we can update the
            # user
            if len(res) == 1:
                y = get_resolver_object(self.resolver)
                if not y.updateable:  # pragma: no cover
                    log.warning(f"The resolver {y!r} is not updateable.")
                else:
                    uid, _rtype, _rname = self.get_user_identifiers()
                    if y.update_user(uid, attributes):
                        success = True
                        # Delete entries corresponding to the old username from the user cache
                        delete_user_cache(username=self.login, resolver=self.resolver)
                        # If necessary, update the username
                        if attributes.get("username"):
                            self.login = attributes.get("username")
                        log.info(f"Successfully updated user {self!r}.")
                    else:  # pragma: no cover
                        log.info(f"user {self!r} failed to update.")

            elif not res:  # pragma: no cover
                log.error(f"The user {self!r} exists in NO resolver.")
        except UserError as exx:  # pragma: no cover
            log.error(f"Error while trying to verify the username: {exx!r}")

        return success

    @log_with(log)
    def delete(self):
        """
        This deletes the user in the user store. I.e. the user in the SQL
        database or the LDAP gets deleted.

        Returns True in case of success
        """
        success = False
        try:
            log.info(f"User {self.login!r}@{self.realm!r} about to be deleted.")
            res = self._get_resolvers()
            # Now we know, the resolvers of this user and we can delete it
            if len(res) == 1:
                y = get_resolver_object(self.resolver)
                if not y.updateable:  # pragma: no cover
                    log.warning(f"The resolver {y!r} is not updateable.")
                else:
                    uid, _rtype, _rname = self.get_user_identifiers()
                    if y.delete_user(uid):
                        success = True
                        log.info(f"Successfully deleted user {self!r}.")
                        # Delete corresponding entry from the user cache
                        delete_user_cache(username=self.login, resolver=self.resolver)
                    else:  # pragma: no cover
                        log.info(f"user {self!r} failed to update.")

            elif not res:  # pragma: no cover
                log.error(f"The user {self!r} exists in NO resolver.")
        except UserError as exx:  # pragma: no cover
            log.error(f"Error while trying to verify the username: {exx!r}")
        except Exception as exx:  # pragma: no cover
            log.error(f"Error checking password within module {exx!r}")
            log.debug(f"{traceback.format_exc()!s}")

        return success


@log_with(log, hide_kwargs=["password"])
def create_user(resolvername, attributes, password=None):
    """
    This creates a new user in the given resolver. The resolver must be
    editable to do so.

    The attributes is a dictionary containing the keys "username", "email",
    "phone",
    "mobile", "surname", "givenname", "password".

    We return the UID and not the user object, since the user could be located
    in several realms!

    :param resolvername: The name of the resolver, in which the user should
        be created
    :type resolvername: basestring
    :param attributes: Attributes of the user
    :type attributes: dict
    :param password: The password of the user
    :return: The uid of the user object
    """
    if password is not None:
        attributes["password"] = password
    y = get_resolver_object(resolvername)
    uid = y.add_user(attributes)
    return uid


@log_with(log)
def split_user(username):
    """
    Split the username of the form user@realm into the username and the realm
    splitting myemail@emailprovider.com@realm is also possible and will
    return (myemail@emailprovider.com, realm).

    If for a user@domain the "domain" does not exist as realm, the name is
    not split, since it might be the user@domain in the default realm

    If the Split@Sign configuration is disabled, the username won't be split
    and the username and an empty realm will be returned.

    We can also split realm\\user to (user, realm)

    :param username: the username to split
    :type username: string
    :return: username and realm
    :rtype: tuple
    """
    user = username.strip()
    realm = ""

    split_at_sign = get_from_config(SYSCONF.SPLITATSIGN, return_bool=True)
    if split_at_sign:
        l = user.split("@")
        if len(l) >= 2:
            if realm_is_defined(l[-1]):
                # split the last only if the last part is really a realm
                (user, realm) = user.rsplit("@", 1)
        else:
            l = user.split("\\")
            if len(l) >= 2:
                (realm, user) = user.rsplit("\\", 1)

    return user, realm


@log_with(log, hide_args_keywords={0: ["pass", "password"]})
def get_user_from_param(param, optionalOrRequired=optional):
    """
    Find the parameter user, realm and resolver and
    create a user object from these parameters.

    An exception is raised, if a user in a realm is found in more
    than one resolver.

    :param param: The dictionary of request parameters
    :type param: dict
    :param optionalOrRequired: whether the user is required
    :type optionalOrRequired: bool
    :return: User as found in the parameters
    :rtype: User object
    """
    realm = ""
    username = getParam(param, "user", optionalOrRequired)

    if username is None:
        username = ""
    else:
        username, realm = split_user(username)

    if "realm" in param:
        realm = param["realm"]

    if username != "":
        if realm is None or realm == "":
            realm = get_default_realm()

    user_object = User(login=username, realm=realm, resolver=param.get("resolver"))

    return user_object


@log_with(log)
def get_user_list(param=None, user=None, custom_attributes=False):
    """
    This function returns a list of user dictionaries.

    :param param: search parameters
    :type param: dict
    :param user:  a specific user object to return
    :type user: User object
    :param custom_attributes:  Set to True, if you want to receive custom attributes
        of external users.
    :type custom_attributes: bool
    :return: list of dictionaries
    """
    users = []
    resolvers = []
    searchDict = {"username": "*"}
    param = param or {}

    # we have to recreate a new searchdict without the realm key
    # as delete does not work
    for key in param:
        lval = param[key]
        if key in ["realm", "resolver", "user", "username"]:
            continue
        searchDict[key] = lval
        log.debug(f"Parameter key:{key!r}={lval!r}")

    # update searchdict depending on existence of 'user' or 'username' in param
    # Since 'user' takes precedence over 'username' we have to check the order
    if "username" in param:
        searchDict["username"] = param["username"]
    if "user" in param:
        searchDict["username"] = param["user"]
    log.debug("Changed search key to username: %s.", searchDict["username"])

    # determine which scope we want to show
    param_resolver = getParam(param, "resolver")
    param_realm = getParam(param, "realm")
    user_resolver = None
    user_realm = None
    if user is not None:
        user_resolver = user.resolver
        user_realm = user.realm

    # Append all possible resolvers
    if param_resolver:
        resolvers.append(param_resolver)
    if user_resolver:
        resolvers.append(user_resolver)
    for pu_realm in [param_realm, user_realm]:
        if pu_realm:
            realm_config = get_realm(pu_realm)
            for r in realm_config.get("resolver", {}):
                if r.get("name"):
                    resolvers.append(r.get("name"))

    if not (param_resolver or user_resolver or param_realm or user_realm):
        # if no realm or resolver was specified, we search the resolvers
        # in all realms
        all_realms = get_realms()
        for _name, res_list in all_realms.items():
            for resolver_entry in res_list.get("resolver"):
                resolvers.append(resolver_entry.get("name"))

    for resolver_name in set(resolvers):
        try:
            log.debug(f"Check for resolver class: {resolver_name!r}")
            y = get_resolver_object(resolver_name)
            log.debug(f"with this search dictionary: {searchDict!r} ")
            ulist = y.getUserList(searchDict)
            # Add resolvername to the list
            realm_id = get_realm_id(param_realm or user_realm)
            for ue in ulist:
                ue["resolver"] = resolver_name
                ue["editable"] = y.editable
            if custom_attributes and realm_id is not None:
                for ue in ulist:
                    # Add the custom attributes, by class method from User
                    # with uid, resolvername and realm_id, which we need to determine by the realm name
                    ue.update(get_attributes(ue.get("userid"), ue.get("resolver"), realm_id))
            log.debug(f"Found this userlist: {ulist!r}")
            users.extend(ulist)

        except KeyError as exx:  # pragma: no cover
            log.error(f"{exx!r}")
            log.debug(f"{traceback.format_exc()!s}")
            raise exx

        except Exception as exx:  # pragma: no cover
            log.error(f"{exx!r}")
            log.debug(f"{traceback.format_exc()!s}")
            continue

    return users


@log_with(log)
@user_cache(cache_username)
def get_username(userid, resolvername):
    """
    Determine the username for a given id and a resolvername.

    :param userid: The id of the user in a resolver
    :type userid: string
    :param resolvername: The name of the resolver
    :return: the username or "" if it does not exist
    :rtype: string
    """
    username = ""
    if userid:
        y = get_resolver_object(resolvername)
        if y:
            username = y.getUsername(userid)
    return username


def log_used_user(user, other_text=""):
    """
    This creates a log message combined of a user and another text.
    The user information is only added, if user.login != user.used_login

    :param user: A user to log
    :type user:  User object
    :param other_text: Some additional text
    :return: str
    """
    return f"logged in as {user.used_login}. {other_text}" if user.used_login != user.login else other_text


def get_attributes(uid, resolver, realm_id):
    """
    Returns the attributes for the given user.

    :param uid: The UID of the user
    :param resolver: The name of the resolver
    :param realm_id: The realm_id
    :return: A dictionary of key/values
    """
    r = {}
    attributes = CustomUserAttribute.query.filter_by(user_id=uid, resolver=resolver, realm_id=realm_id).all()
    for attr in attributes:
        r[attr.Key] = attr.Value
    return r


def is_attribute_at_all():
    """
    Check if there are custom user attributes at all
    :return: bool
    """
    return bool(CustomUserAttribute.query.count())
