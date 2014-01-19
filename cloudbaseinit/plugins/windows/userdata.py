# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Cloudbase Solutions Srl
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import email

from cloudbaseinit.metadata.services import base as metadata_services_base
from cloudbaseinit.openstack.common import log as logging
from cloudbaseinit.plugins import base
from cloudbaseinit.plugins.windows import userdatautils
from cloudbaseinit.plugins.windows.userdataplugins import factory

LOG = logging.getLogger(__name__)


class UserDataPlugin(base.BasePlugin):
    _part_handler_content_type = "text/part-handler"

    def execute(self, service, shared_data):
        try:
            user_data = service.get_user_data('openstack')
        except metadata_services_base.NotExistingMetadataException:
            return (base.PLUGIN_EXECUTION_DONE, False)

        if not user_data:
            return (base.PLUGIN_EXECUTION_DONE, False)

        return self._process_user_data(user_data)

    def _parse_mime(self, user_data):
        return email.message_from_string(user_data).walk()

    def _process_user_data(self, user_data):
        plugin_status = base.PLUGIN_EXECUTION_DONE
        reboot = False

        LOG.debug('User data content:\n%s' % user_data)
        if user_data.startswith('Content-Type: multipart'):
            user_data_plugins_factory = factory.UserDataPluginsFactory()
            user_data_plugins = user_data_plugins_factory.load_plugins()
            user_handlers = {}

            for part in self._parse_mime(user_data):
                (plugin_status, reboot) = self._process_part(part,
                                                             user_data_plugins,
                                                             user_handlers)
                if reboot:
                    break

            return (plugin_status, reboot)
        else:
            return self._process_non_multi_part(user_data)

    def _process_part(self, part, user_data_plugins, user_handlers):
        ret_val = None
        content_type = part.get_content_type()
        user_data_plugin = user_data_plugins.get(content_type)
        if not user_data_plugin:
            LOG.info("Userdata plugin not found for content type: %s" %
                     content_type)
        else:
            try:
                if content_type == self._part_handler_content_type:
                    user_handlers.update(user_data_plugin.process(part))
                else:
                    handler_func = user_handlers.get(part.get_content_type())
                    self._begin_part_process_event(part, handler_func)

                    LOG.info("Executing user data plugin: %s" %
                             user_data_plugin.__class__.__name__)

                    ret_val = user_data_plugin.process(part)

                    self._end_part_process_event(part, handler_func)
            except Exception, ex:
                LOG.error('Exception during multipart part handling: '
                          '%(content_type)s, %(filename)s' %
                          {'content_type': part.get_content_type(),
                           'filename': part.get_filename()})
                LOG.exception(ex)

        return self._get_plugin_return_value(ret_val)

    def _begin_part_process_event(self, part, handler_func):
        if handler_func:
            handler_func("", "__begin__", part.get_filename(),
                         part.get_payload())

    def _end_part_process_event(self, part, handler_func):
        if handler_func:
            handler_func("", "__end__", part.get_filename(),
                         part.get_payload())

    def _get_plugin_return_value(self, ret_val):
        plugin_status = base.PLUGIN_EXECUTION_DONE
        reboot = False

        if ret_val >= 1001 and ret_val <= 1003:
            reboot = bool(ret_val & 1)
            if ret_val & 2:
                plugin_status = base.PLUGIN_EXECUTE_ON_NEXT_BOOT

        return (plugin_status, reboot)

    def _process_non_multi_part(self, user_data):
        ret_val = userdatautils.execute_user_data_script(user_data)
        return self._get_plugin_return_value(ret_val)
