from avocado import Test
from avocado_cloud.app import Setup
import os
import time


class NetworkTest(Test):
    def setUp(self):
        self.cloud = Setup(self.params, self.name)
        self.vm = self.cloud.vm
        self.pwd = os.path.abspath(os.path.dirname(__file__))
        pre_delete = False
        pre_stop = False
        if self.name.name.endswith("test_coldplug_nics"):
            pre_stop = True
        if not self.vm.nic_count or self.vm.nic_count < 2:
            self.cancel("No nic count. Skip this case.")
        self.session = self.cloud.init_vm(pre_delete=pre_delete,
                                          pre_stop=pre_stop)
        if self.name.name.endswith("test_hotplug_nics") or \
           self.name.name.endswith("test_coldplug_nics"):
            self.cloud.init_nics(self.vm.nic_count)
            self.primary_nic_id = self.cloud.primary_nic_id

    def test_hotplug_nics(self):
        """
        1. Start VM. Attach max NICs and check all can get IP
        2. Add 1 more NIC. Should not be added
        3. Detach all NICs. Device should be removed inside guest
        """
        # 1. Attach max NICs and check all can get IP
        count = self.vm.nic_count - 1
        self.log.info("Step 1: Attach %s NICs." % count)
        self.vm.attach_nics(count, wait=True)
        self.assertEqual(len(self.vm.query_nics()), count + 1,
                         "Total NICs number is not %d" % (count + 1))

        guest_path = self.session.cmd_output("echo $HOME") + "/workspace"
        self.session.cmd_output("mkdir -p {0}".format(guest_path))

        self.session.copy_files_to(
            local_path="{0}/../../scripts/aliyun_enable_nics.sh".format(
                self.pwd),
            remote_path=guest_path)

        self.log.info("NIC Count: %s" % count)
        self.session.cmd_output("bash {0}/aliyun_enable_nics.sh {1}".format(
            guest_path, count),
                                timeout=180)

        self.session.cmd_output('ip addr', timeout=30)
        time.sleep(60)  # waiting for dhcp works
        self.session.cmd_output('ip addr', timeout=30)

        time.sleep(10)
        outside_ips = [
            str(self.vm.get_private_ip_address(nic))
            for nic in self.vm.query_nics()
        ]
        inside_ips = self.session.cmd_output("ip addr")
        for outside_ip in outside_ips:
            self.assertIn(
                outside_ip, inside_ips, "Some of NICs are not available. "
                "Outside IP: %s Inside IPs:\n %s" % (outside_ip, inside_ips))

        # 2. Add 1 more NIC. Should not be added
        self.log.info("Step 2: Add 1 more NIC, should not be added.")
        self.vm.attach_nics(1)
        self.assertEqual(
            len(self.vm.query_nics()), count + 1,
            "NICs number should not greater than %d" % (count + 1))

        # 3. Detach all NICs. NICs should be removed inside guest
        self.log.info("Step 3: Detach all NICs")

        self.session.copy_files_to(
            local_path="{0}/../../scripts/aliyun_disable_nics.sh".format(
                self.pwd),
            remote_path=guest_path)

        self.log.info("NIC Count: %s" % count)
        self.session.cmd_output("bash {0}/aliyun_disable_nics.sh {1}".format(
            guest_path, count),
                                timeout=180)

        nic_ids = [
            self.vm.get_nic_id(nic) for nic in self.vm.query_nics()
            if self.vm.get_nic_id(nic) != self.primary_nic_id
        ]
        self.vm.detach_nics(nic_ids, wait=True)
        self.assertEqual(len(self.vm.query_nics()), 1,
                         "Fail to remove all NICs outside guest")
        time.sleep(5)
        self.assertEqual(
            self.session.cmd_output(
                "ip addr | grep -e 'eth.*mtu' -e 'ens.*mtu' | wc -l"), "1",
            "Fail to remove all NICs inside guest")

        self.log.info("Detach all NICs successfully")

    def test_coldplug_nics(self):
        """
        1. Stop VM. Attach max NICs. Start VM and check all can get IP
        2. Stop VM. Add 1 more NIC. Should not be added
        3. Stop VM. Detach all NICs. Device should be removed inside guest
        """
        # Set timeout for Alibaba baremetal
        if 'ecs.ebm' in self.vm.flavor:
            connect_timeout = 600
        else:
            connect_timeout = 120

        # 1. Attach max NICs and check all can get IP
        count = self.vm.nic_count - 1
        self.log.info("Step 1: Attach %s NICs." % count)
        self.vm.attach_nics(count, wait=True)
        self.assertEqual(len(self.vm.query_nics()), count + 1,
                         "Total NICs number is not %d" % (count + 1))
        self.vm.start(wait=True)
        self.session.connect(timeout=connect_timeout)

        guest_path = self.session.cmd_output("echo $HOME") + "/workspace"
        self.session.cmd_output("mkdir -p {0}".format(guest_path))

        self.session.copy_files_to(
            local_path="{0}/../../scripts/aliyun_enable_nics.sh".format(
                self.pwd),
            remote_path=guest_path)

        self.log.info("NIC Count: %s" % count)
        self.session.cmd_output("bash {0}/aliyun_enable_nics.sh {1}".format(
            guest_path, count),
                                timeout=180)

        time.sleep(10)
        self.session.cmd_output('ip addr', timeout=30)

        outside_ips = [
            self.vm.get_private_ip_address(nic)
            for nic in self.vm.query_nics()
        ]
        inside_ips = self.session.cmd_output("ip addr")
        for outside_ip in outside_ips:
            self.assertIn(
                outside_ip, inside_ips,
                "Some of NICs are not available. Inside IPs: %s" % inside_ips)

        # 2. Add 1 more NIC. Should not be added
        self.log.info("Step 2: Add 1 more NIC, should not be added.")
        self.vm.stop(wait=True)
        self.assertTrue(self.vm.is_stopped(), "Fail to stop VM")
        self.vm.attach_nics(1)
        self.assertEqual(
            len(self.vm.query_nics()), count + 1,
            "NICs number should not greater than %d" % (count + 1))

        # 3. Detach all NICs. NICs should be removed inside guest
        self.log.info("Step 3: Detach all NICs.")
        nic_ids = [
            self.vm.get_nic_id(nic) for nic in self.vm.query_nics()
            if self.vm.get_nic_id(nic) != self.primary_nic_id
        ]
        self.vm.detach_nics(nic_ids, wait=True)
        self.assertEqual(len(self.vm.query_nics()), 1,
                         "Fail to remove all NICs outside guest")
        self.vm.start(wait=True)
        self.assertTrue(self.vm.is_started(), "Fail to start VM")
        self.session.connect(timeout=connect_timeout)
        guest_cmd = "ip addr | grep -e 'eth.*mtu' -e 'ens.*mtu' | wc -l"

        self.assertEqual(self.session.cmd_output(guest_cmd), "1",
                         "Fail to remove all NICs inside guest")
        self.log.info("Detach all NICs successfully")

    def tearDown(self):
        if self.name.name.endswith("test_hotplug_nics") or \
           self.name.name.endswith("test_coldplug_nics"):
            guest_cmd = """
primary_nic=$(ifconfig | grep "flags=.*\<UP\>" | cut -d: -f1 | \
grep -e eth -e ens | head -n 1)
device_name=$(echo $primary_nic | tr -d '[:digit:]')
ls /etc/sysconfig/network-scripts/ifcfg-${device_name}* | \
grep -v ${primary_nic} | xargs sudo rm -f
"""
            self.session.cmd_output(guest_cmd, timeout=180)
        self.session.close()
