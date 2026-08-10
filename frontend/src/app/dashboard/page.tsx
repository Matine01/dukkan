"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import * as api from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<api.User | null>(null);
  const [vms, setVMs] = useState<api.VirtualMachine[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateWizard, setShowCreateWizard] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      const [userData, vmData] = await Promise.all([
        api.getCurrentUser(),
        api.getVMs(),
      ]);

      if (!userData) {
        router.push("/login");
        return;
      }

      setUser(userData);
      setVMs(vmData);
    } catch (error) {
      console.error("Failed to load data:", error);
    } finally {
      setLoading(false);
    }
  }

  async function handleVMAction(vmId: string, action: "start" | "stop" | "restart" | "delete") {
    if (!confirm(`Are you sure you want to ${action} this VM?`)) return;

    try {
      switch (action) {
        case "start":
          await api.startVM(vmId);
          break;
        case "stop":
          await api.stopVM(vmId);
          break;
        case "restart":
          await api.restartVM(vmId);
          break;
        case "delete":
          await api.deleteVM(vmId);
          break;
      }
      loadData();
    } catch (error) {
      alert(error instanceof Error ? error.message : `Failed to ${action} VM`);
    }
  }

  function getStatusColor(status: string) {
    switch (status) {
      case "running":
        return "bg-green-100 text-green-800";
      case "stopped":
        return "bg-gray-100 text-gray-800";
      case "starting":
      case "stopping":
      case "restarting":
        return "bg-yellow-100 text-yellow-800";
      case "error":
        return "bg-red-100 text-red-800";
      default:
        return "bg-gray-100 text-gray-800";
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
          <h1 className="text-2xl font-bold text-gray-900">Dukkan Cloud</h1>
          <div className="flex items-center space-x-4">
            <span className="text-sm text-gray-600">{user?.email}</span>
            <button
              onClick={async () => {
                await api.logout();
                router.push("/login");
              }}
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-white p-6 rounded-lg shadow">
            <h3 className="text-sm font-medium text-gray-500">Total VMs</h3>
            <p className="text-3xl font-bold text-gray-900">{vms.length}</p>
          </div>
          <div className="bg-white p-6 rounded-lg shadow">
            <h3 className="text-sm font-medium text-gray-500">Running</h3>
            <p className="text-3xl font-bold text-green-600">
              {vms.filter((vm) => vm.status === "running").length}
            </p>
          </div>
          <div className="bg-white p-6 rounded-lg shadow">
            <h3 className="text-sm font-medium text-gray-500">Stopped</h3>
            <p className="text-3xl font-bold text-gray-600">
              {vms.filter((vm) => vm.status === "stopped").length}
            </p>
          </div>
          <div className="bg-white p-6 rounded-lg shadow">
            <h3 className="text-sm font-medium text-gray-500">Quota</h3>
            <p className="text-3xl font-bold text-blue-600">
              {vms.length}/{user?.max_vms || 3}
            </p>
          </div>
        </div>

        {/* VM List */}
        <div className="bg-white rounded-lg shadow">
          <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
            <h2 className="text-lg font-semibold text-gray-900">Virtual Machines</h2>
            <button
              onClick={() => setShowCreateWizard(true)}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
            >
              Create VM
            </button>
          </div>

          {vms.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <p className="text-gray-500 mb-4">No virtual machines yet</p>
              <button
                onClick={() => setShowCreateWizard(true)}
                className="text-blue-600 hover:text-blue-800"
              >
                Create your first VM →
              </button>
            </div>
          ) : (
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Name
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    IP Address
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Resources
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {vms.map((vm) => (
                  <tr key={vm.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Link
                        href={`/dashboard/vms/${vm.id}`}
                        className="text-blue-600 hover:text-blue-800 font-medium"
                      >
                        {vm.name}
                      </Link>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-600 uppercase">{vm.vm_type}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-600">{vm.ip_address || "-"}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-600">
                        {vm.cpu_cores} vCPU • {vm.ram_gb} GB • {vm.disk_gb} GB
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span
                        className={cn(
                          "px-2 py-1 text-xs font-medium rounded-full",
                          getStatusColor(vm.status)
                        )}
                      >
                        {vm.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                      {formatDate(vm.created_at)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      {vm.status === "stopped" && (
                        <button
                          onClick={() => handleVMAction(vm.id, "start")}
                          className="text-green-600 hover:text-green-800 mr-3"
                        >
                          Start
                        </button>
                      )}
                      {vm.status === "running" && (
                        <>
                          <button
                            onClick={() => handleVMAction(vm.id, "stop")}
                            className="text-red-600 hover:text-red-800 mr-3"
                          >
                            Stop
                          </button>
                          <button
                            onClick={() => handleVMAction(vm.id, "restart")}
                            className="text-yellow-600 hover:text-yellow-800 mr-3"
                          >
                            Restart
                          </button>
                        </>
                      )}
                      <button
                        onClick={() => handleVMAction(vm.id, "delete")}
                        className="text-red-600 hover:text-red-800"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>

      {/* Create VM Modal */}
      {showCreateWizard && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <api.VMCreateWizard
            onSuccess={() => {
              setShowCreateWizard(false);
              loadData();
            }}
            onCancel={() => setShowCreateWizard(false)}
          />
        </div>
      )}
    </div>
  );
}

// Import the wizard component dynamically to avoid SSR issues
import { VMCreateWizard } from "@/components/dashboard/VMCreateWizard";
api.VMCreateWizard = VMCreateWizard;
