/**
 * API Client for Dukkan Cloud Backend
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// Types
export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: "superadmin" | "org_admin" | "member" | "viewer";
  organization_id: string | null;
  max_vms: number;
  created_at: string;
}

export interface VirtualMachine {
  id: string;
  proxmox_vmid: number;
  name: string;
  hostname: string;
  ip_address: string | null;
  status: "stopped" | "running" | "starting" | "stopping" | "restarting" | "error";
  vm_type: "lxc" | "qemu";
  cpu_cores: number;
  ram_gb: number;
  disk_gb: number;
  guac_protocol: string | null;
  owner_id: string;
  organization_id: string;
  created_at: string;
}

export interface VMWithGuacamole extends VirtualMachine {
  guac_url?: string;
  guac_credentials?: {
    username: string;
    protocol: string;
  };
}

export interface Network {
  id: string;
  name: string;
  cidr: string;
  network_type: "vpc" | "public" | "private";
  vlan_id: number | null;
  gateway: string | null;
  organization_id: string;
  created_at: string;
}

export interface Volume {
  id: string;
  name: string;
  size_gb: number;
  volume_type: "ssd" | "hdd" | "nvme";
  status: "available" | "in_use" | "attaching" | "detaching" | "error";
  organization_id: string;
  attached_to_id: string | null;
  created_at: string;
}

export interface BillingSummary {
  current_period: string;
  total_usage: number;
  total_cost: number;
  vm_count: number;
  volume_count: number;
  breakdown: Record<string, number>;
}

// Auth functions
export async function login(email: string, password: string): Promise<{ access_token: string }> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "include",
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Login failed");
  }

  return response.json();
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE_URL}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}

export async function getCurrentUser(): Promise<User | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/auth/me`, {
      credentials: "include",
    });

    if (!response.ok) {
      return null;
    }

    return response.json();
  } catch {
    return null;
  }
}

// VM functions
export async function getVMs(statusFilter?: string, vmType?: string): Promise<VirtualMachine[]> {
  const params = new URLSearchParams();
  if (statusFilter) params.set("status_filter", statusFilter);
  if (vmType) params.set("vm_type", vmType);

  const response = await fetch(`${API_BASE_URL}/vms?${params}`, {
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch VMs");
  }

  return response.json();
}

export async function createLXC(data: {
  name: string;
  hostname: string;
  template_id: number;
  cpu_cores: number;
  ram_gb: number;
  disk_gb: number;
  cloud_init?: {
    username: string;
    password: string;
    ssh_keys?: string[];
  };
}): Promise<VirtualMachine> {
  const response = await fetch(`${API_BASE_URL}/vms/lxc`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to create LXC");
  }

  return response.json();
}

export async function createQEMU(data: {
  name: string;
  hostname: string;
  template_id: number;
  os_type: "linux" | "windows";
  cpu_cores: number;
  ram_gb: number;
  disk_gb: number;
  cloud_init?: {
    username: string;
    password: string;
    ssh_keys?: string[];
  };
}): Promise<VirtualMachine> {
  const response = await fetch(`${API_BASE_URL}/vms/qemu`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to create QEMU VM");
  }

  return response.json();
}

export async function getVM(vmId: string): Promise<VMWithGuacamole> {
  const response = await fetch(`${API_BASE_URL}/vms/${vmId}`, {
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch VM");
  }

  return response.json();
}

export async function startVM(vmId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/vms/${vmId}/start`, {
    method: "POST",
    credentials: "include",
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to start VM");
  }
}

export async function stopVM(vmId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/vms/${vmId}/stop`, {
    method: "POST",
    credentials: "include",
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to stop VM");
  }
}

export async function restartVM(vmId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/vms/${vmId}/restart`, {
    method: "POST",
    credentials: "include",
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to restart VM");
  }
}

export async function deleteVM(vmId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/vms/${vmId}`, {
    method: "DELETE",
    credentials: "include",
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to delete VM");
  }
}

// Network functions
export async function getNetworks(): Promise<Network[]> {
  const response = await fetch(`${API_BASE_URL}/networks`, {
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch networks");
  }

  return response.json();
}

export async function createNetwork(data: {
  name: string;
  cidr: string;
  network_type: "vpc" | "public" | "private";
  gateway?: string;
}): Promise<Network> {
  const response = await fetch(`${API_BASE_URL}/networks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to create network");
  }

  return response.json();
}

// Volume functions
export async function getVolumes(): Promise<Volume[]> {
  const response = await fetch(`${API_BASE_URL}/volumes`, {
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch volumes");
  }

  return response.json();
}

export async function createVolume(data: {
  name: string;
  size_gb: number;
  volume_type: "ssd" | "hdd" | "nvme";
}): Promise<Volume> {
  const response = await fetch(`${API_BASE_URL}/volumes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to create volume");
  }

  return response.json();
}

// Billing functions
export async function getBillingSummary(period?: string): Promise<BillingSummary> {
  const params = period ? `?period=${period}` : "";
  const response = await fetch(`${API_BASE_URL}/billing/summary${params}`, {
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch billing summary");
  }

  return response.json();
}

// WebSocket console connection
export function createConsoleWebSocket(vmId: string, token: string): WebSocket {
  const wsUrl = `ws://${window.location.host}/api/v1/vms/ws/console/${vmId}?token=${token}`;
  return new WebSocket(wsUrl);
}
