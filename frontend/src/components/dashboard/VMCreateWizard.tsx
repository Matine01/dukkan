"use client";

import { useState } from "react";
import * as api from "@/lib/api";
import { cn } from "@/lib/utils";

interface VMCreateWizardProps {
  onSuccess?: (vm: api.VirtualMachine) => void;
  onCancel?: () => void;
}

export function VMCreateWizard({ onSuccess, onCancel }: VMCreateWizardProps) {
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [formData, setFormData] = useState({
    vmType: "qemu" as "lxc" | "qemu",
    name: "",
    hostname: "",
    templateId: 9000,
    osType: "linux" as "linux" | "windows",
    cpuCores: 2,
    ramGb: 4,
    diskGb: 50,
    username: "ubuntu",
    password: "",
    sshKey: "",
  });

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);

    try {
      const cloudInit = {
        username: formData.username,
        password: formData.password,
        ssh_keys: formData.sshKey ? [formData.sshKey.trim()] : undefined,
      };

      let vm: api.VirtualMachine;

      if (formData.vmType === "lxc") {
        vm = await api.createLXC({
          name: formData.name,
          hostname: formData.hostname,
          template_id: formData.templateId,
          cpu_cores: formData.cpuCores,
          ram_gb: formData.ramGb,
          disk_gb: formData.diskGb,
          cloud_init,
        });
      } else {
        vm = await api.createQEMU({
          name: formData.name,
          hostname: formData.hostname,
          template_id: formData.templateId,
          os_type: formData.osType,
          cpu_cores: formData.cpuCores,
          ram_gb: formData.ramGb,
          disk_gb: formData.diskGb,
          cloud_init,
        });
      }

      onSuccess?.(vm);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create VM");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-2xl bg-white rounded-lg shadow-lg p-6">
      {/* Progress Steps */}
      <div className="flex items-center justify-between mb-8">
        {[1, 2, 3].map((s) => (
          <div key={s} className="flex items-center">
            <div
              className={cn(
                "w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium",
                step >= s ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-600"
              )}
            >
              {s}
            </div>
            {s < 3 && (
              <div
                className={cn(
                  "w-24 h-1 mx-2",
                  step > s ? "bg-blue-600" : "bg-gray-200"
                )}
              />
            )}
          </div>
        ))}
      </div>

      {/* Step Content */}
      {step === 1 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Choose VM Type</h2>
          
          <div className="grid grid-cols-2 gap-4">
            <button
              onClick={() => setFormData({ ...formData, vmType: "lxc" })}
              className={cn(
                "p-4 border-2 rounded-lg text-left transition-colors",
                formData.vmType === "lxc"
                  ? "border-blue-600 bg-blue-50"
                  : "border-gray-200 hover:border-gray-300"
              )}
            >
              <h3 className="font-medium">LXC Container</h3>
              <p className="text-sm text-gray-500 mt-1">
                Lightweight, fast boot times, shared kernel
              </p>
            </button>
            
            <button
              onClick={() => setFormData({ ...formData, vmType: "qemu" })}
              className={cn(
                "p-4 border-2 rounded-lg text-left transition-colors",
                formData.vmType === "qemu"
                  ? "border-blue-600 bg-blue-50"
                  : "border-gray-200 hover:border-gray-300"
              )}
            >
              <h3 className="font-medium">QEMU VM</h3>
              <p className="text-sm text-gray-500 mt-1">
                Full virtualization, isolated kernel, any OS
              </p>
            </button>
          </div>

          <div className="flex justify-end mt-6">
            <button
              onClick={() => setStep(2)}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Configure Resources</h2>
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Name</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                placeholder="my-vm"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700">Hostname</label>
              <input
                type="text"
                value={formData.hostname}
                onChange={(e) => setFormData({ ...formData, hostname: e.target.value })}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                placeholder="my-vm.local"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">CPU Cores</label>
              <input
                type="number"
                value={formData.cpuCores}
                onChange={(e) => setFormData({ ...formData, cpuCores: parseInt(e.target.value) || 1 })}
                min={1}
                max={64}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700">RAM (GB)</label>
              <input
                type="number"
                value={formData.ramGb}
                onChange={(e) => setFormData({ ...formData, ramGb: parseInt(e.target.value) || 1 })}
                min={1}
                max={512}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700">Disk (GB)</label>
              <input
                type="number"
                value={formData.diskGb}
                onChange={(e) => setFormData({ ...formData, diskGb: parseInt(e.target.value) || 10 })}
                min={10}
                max={4096}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
              />
            </div>
          </div>

          <div className="flex justify-between mt-6">
            <button
              onClick={() => setStep(1)}
              className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
            >
              Back
            </button>
            <button
              onClick={() => setStep(3)}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Authentication</h2>
          
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Username</label>
              <input
                type="text"
                value={formData.username}
                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                placeholder="ubuntu"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700">Password</label>
              <input
                type="password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                placeholder="••••••••"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700">SSH Public Key (optional)</label>
              <textarea
                value={formData.sshKey}
                onChange={(e) => setFormData({ ...formData, sshKey: e.target.value })}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                rows={3}
                placeholder="ssh-rsa AAAA..."
              />
            </div>
          </div>

          {error && (
            <div className="p-3 bg-red-50 text-red-700 rounded-md text-sm">
              {error}
            </div>
          )}

          <div className="flex justify-between mt-6">
            <button
              onClick={() => setStep(2)}
              className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
            >
              Back
            </button>
            <button
              onClick={handleSubmit}
              disabled={loading}
              className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50"
            >
              {loading ? "Creating..." : "Create VM"}
            </button>
          </div>
        </div>
      )}

      {/* Cancel button */}
      {onCancel && (
        <button
          onClick={onCancel}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
        >
          ✕
        </button>
      )}
    </div>
  );
}
