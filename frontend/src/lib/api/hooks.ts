import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

// System hooks
export function useSystemStatus() {
  return useQuery({
    queryKey: ['systemStatus'],
    queryFn: api.getStatus,
    refetchInterval: 5000,
  })
}

export function useBriefing() {
  return useQuery({
    queryKey: ['briefing'],
    queryFn: api.getBriefing,
    refetchInterval: 15000,
  })
}

export function usePipeline() {
  return useQuery({
    queryKey: ['pipeline'],
    queryFn: api.getPipeline,
    refetchInterval: 15000,
  })
}

export function useOpportunities(params?: { q?: string; status?: string; signal_type?: string; limit?: number; offset?: number }) {
  return useQuery({ queryKey: ['opportunities', params], queryFn: () => api.getOpportunities(params), refetchInterval: 10000 })
}

export function useOpportunity(id?: string) {
  return useQuery({ queryKey: ['opportunity', id], queryFn: () => api.getOpportunity(id!), enabled: Boolean(id) })
}

export function useDecision(id?: string) {
  return useQuery({ queryKey: ['decision', id], queryFn: () => api.getDecision(id!), enabled: Boolean(id) })
}

export function useActionTimeline(id?: string) {
  return useQuery({ queryKey: ['actionTimeline', id], queryFn: () => api.getActionTimeline(id!), enabled: Boolean(id) })
}

export function useLearningChanges() {
  return useQuery({ queryKey: ['learningChanges'], queryFn: api.getLearningChanges, refetchInterval: 15000 })
}

export function usePolicyHistory() {
  return useQuery({ queryKey: ['policyHistory'], queryFn: api.getPolicyHistory, refetchInterval: 30000 })
}

export function useScope() {
  return useQuery({ queryKey: ['scope'], queryFn: api.getScope, refetchInterval: 30000 })
}

export function useSetScope() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: api.setScope, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['scope'] }) })
}

export function useAuditExplain(id?: string) {
  return useQuery({
    queryKey: ['auditExplain', id],
    queryFn: () => api.getAuditExplain(id!),
    enabled: Boolean(id),
  })
}

export function usePause() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.pause,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['systemStatus'] })
    },
  })
}

export function useStop() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.stop,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['systemStatus'] })
    },
  })
}

export function useResume() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.resume,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['systemStatus'] })
    },
  })
}

export function useSetMode() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.setMode,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['systemStatus'] })
    },
  })
}

// Queue hooks
export function useQueue() {
  return useQuery({
    queryKey: ['queue'],
    queryFn: api.getQueue,
    refetchInterval: 5000,
  })
}

export function useApproveAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) => api.approveAction(id, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
      queryClient.invalidateQueries({ queryKey: ['systemStatus'] })
      queryClient.invalidateQueries({ queryKey: ['pipeline'] })
      queryClient.invalidateQueries({ queryKey: ['opportunities'] })
      queryClient.invalidateQueries({ queryKey: ['decision'] })
    },
  })
}

export function useRejectAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => api.rejectAction(id, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
      queryClient.invalidateQueries({ queryKey: ['systemStatus'] })
      queryClient.invalidateQueries({ queryKey: ['opportunities'] })
      queryClient.invalidateQueries({ queryKey: ['decision'] })
    },
  })
}

export function useEditAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, changes, note }: { id: string; changes: { subject?: string; body?: string }; note?: string }) => 
      api.editAction(id, changes, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue'] })
      queryClient.invalidateQueries({ queryKey: ['activity'] })
      queryClient.invalidateQueries({ queryKey: ['systemStatus'] })
    },
  })
}

// Activity hooks
export function useActivity(params?: { limit?: number; offset?: number; filter?: string }) {
  return useQuery({
    queryKey: ['activity', params],
    queryFn: () => api.getActivity(params),
    refetchInterval: 10000,
  })
}

// Variants hooks
export function useVariants() {
  return useQuery({
    queryKey: ['variants'],
    queryFn: api.getVariants,
    refetchInterval: 30000,
  })
}

// Policy hooks
export function usePolicy() {
  return useQuery({
    queryKey: ['policy'],
    queryFn: api.getPolicy,
    refetchInterval: 30000,
  })
}

export function useUpdatePolicy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.updatePolicy,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['policy'] })
    },
  })
}

export function useRollbackPolicy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.rollbackPolicy,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['policy'] })
    },
  })
}

// Warm Graph hooks
export function useWarmEdges() {
  return useQuery({
    queryKey: ['warmEdges'],
    queryFn: api.getWarmEdges,
    refetchInterval: 30000,
  })
}

export function useCompanies() {
  return useQuery({ queryKey: ['companies'], queryFn: api.getCompanies, refetchInterval: 30000 })
}

export function useContacts(companyId?: string) {
  return useQuery({ queryKey: ['contacts', companyId], queryFn: () => api.getContacts(companyId), refetchInterval: 30000 })
}
