"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardFooter } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger, DialogDescription } from "@/components/ui/dialog"
import { 
  Mail, 
  Link,
  User, 
  Building, 
  FileText, 
  Edit, 
  Check, 
  X,
  Clock,
  Target,
  TrendingUp
} from "lucide-react"
import { useApproveAction, useRejectAction, useEditAction } from "@/lib/api/hooks"
import type { Action, EvidenceLink, GuardrailCheck, LearningDelta } from "@/lib/api/client"

interface DecisionCardProps {
  action: Action
}

export function DecisionCard({ action }: DecisionCardProps) {
  const [showEditDialog, setShowEditDialog] = React.useState(false)
  const [showRejectDialog, setShowRejectDialog] = React.useState(false)
  const [editNote, setEditNote] = React.useState("")
  const [rejectReason, setRejectReason] = React.useState("")
  const [editedContent, setEditedContent] = React.useState(action.decision_trace?.what || "")
  
  const approveMutation = useApproveAction()
  const rejectMutation = useRejectAction()
  const editMutation = useEditAction()

  const handleApprove = () => {
    approveMutation.mutate({ id: action.id, note: editNote })
    setShowEditDialog(false)
    setEditNote("")
  }

  const handleReject = () => {
    if (rejectReason.trim()) {
      rejectMutation.mutate({ id: action.id, reason: rejectReason })
      setShowRejectDialog(false)
      setRejectReason("")
    }
  }

  const handleEdit = () => {
    editMutation.mutate({ 
      id: action.id, 
      changes: { subject: editedContent, body: editedContent },
      note: editNote
    })
    setShowEditDialog(false)
    setEditNote("")
    setEditedContent(action.decision_trace?.what || "")
  }

  const trace = action.decision_trace

  if (!trace) {
    return (
      <Card className="border-l-4 border-l-primary">
        <CardContent className="p-6">
          <p className="text-muted-foreground">No decision trace available for this action.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="border-l-4 border-l-primary hover:shadow-md transition-shadow">
      <div className="p-6 pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant={action.channel === 'EMAIL' ? "default" : "secondary"} className="gap-1">
                {action.channel === 'EMAIL' ? <Mail className="h-3 w-3" /> : <Link className="h-3 w-3" />}
                {action.channel}
              </Badge>
              <Badge variant="outline">{action.action_type.replace('_', ' ')}</Badge>
              <Badge variant="outline">{action.segment}</Badge>
            </div>
            <p className="mt-2 text-sm text-muted-foreground truncate">
              {trace.what}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className={cn(
              "w-2 h-2 rounded-full",
              action.status === 'PROPOSED' && "bg-yellow-500",
              action.status === 'APPROVED' && "bg-green-500",
              action.status === 'REJECTED' && "bg-red-500",
              action.status === 'EDITED' && "bg-blue-500",
            )} />
            <span className="text-xs font-medium capitalize">{action.status.toLowerCase()}</span>
          </div>
        </div>
      </div>

      <CardContent className="pb-3 px-6">
        <Tabs defaultValue="what" className="w-full">
          <TabsList className="grid w-full grid-cols-6">
            <TabsTrigger value="what" className="text-xs">What</TabsTrigger>
            <TabsTrigger value="why" className="text-xs">Why</TabsTrigger>
            <TabsTrigger value="evidence" className="text-xs">Evidence</TabsTrigger>
            <TabsTrigger value="guardrails" className="text-xs">Guardrails</TabsTrigger>
            <TabsTrigger value="learned" className="text-xs">Learned</TabsTrigger>
            <TabsTrigger value="next" className="text-xs">Next</TabsTrigger>
          </TabsList>

          <TabsContent value="what" className="mt-4">
            <div className="space-y-3">
              <div>
                <Label className="text-xs font-medium text-muted-foreground">Action Details</Label>
                <p className="mt-1 text-sm">{trace.what}</p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <DetailRow label="Target" value={`${action.opportunity_id}`} icon={User} />
                <DetailRow label="Channel" value={action.channel} icon={action.channel === 'EMAIL' ? Mail : Link} />
                <DetailRow label="Variant" value={action.variant_id} icon={FileText} />
                <DetailRow label="Timing" value={action.timing} icon={Clock} />
                <DetailRow label="Confidence" value={`${Math.round(action.confidence * 100)}%`} icon={Target} />
                <DetailRow label="Expected Effect" value={trace.next_steps} icon={TrendingUp} />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="why" className="mt-4">
            <div className="space-y-3">
              <Label className="text-xs font-medium text-muted-foreground">Reasoning</Label>
              <p className="text-sm">{trace.why}</p>
            </div>
          </TabsContent>

          <TabsContent value="evidence" className="mt-4">
            <div className="space-y-2">
              <Label className="text-xs font-medium text-muted-foreground">Evidence Links</Label>
              {trace.evidence.length === 0 ? (
                <p className="text-sm text-muted-foreground">No evidence links available</p>
              ) : (
                <div className="space-y-2">
                  {trace.evidence.map((evidence, i) => (
                    <EvidenceItem key={i} evidence={evidence} />
                  ))}
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="guardrails" className="mt-4">
            <div className="space-y-2">
              <Label className="text-xs font-medium text-muted-foreground">Guardrail Checks</Label>
              {trace.guardrails.length === 0 ? (
                <p className="text-sm text-muted-foreground">No guardrail checks recorded</p>
              ) : (
                <div className="space-y-2">
                  {trace.guardrails.map((guardrail, i) => (
                    <GuardrailItem key={i} guardrail={guardrail} />
                  ))}
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="learned" className="mt-4">
            <div className="space-y-2">
              <Label className="text-xs font-medium text-muted-foreground">Learning Deltas</Label>
              {trace.learned.length === 0 ? (
                <p className="text-sm text-muted-foreground">No learning deltas recorded</p>
              ) : (
                <div className="space-y-2">
                  {trace.learned.map((learned, i) => (
                    <LearnedItem key={i} learned={learned} />
                  ))}
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="next" className="mt-4">
            <div className="space-y-3">
              <Label className="text-xs font-medium text-muted-foreground">Next Steps</Label>
              <p className="text-sm">{trace.next_steps}</p>
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>

      <CardFooter className="pt-3 border-t px-6">
        <div className="flex items-center justify-end gap-2 w-full">
          <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1">
                <Edit className="h-3 w-3" />
                Edit
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle>Edit Action</DialogTitle>
                <DialogDescription>Modify the action content and add a note</DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div>
                  <Label htmlFor="edit-content" className="block text-sm font-medium mb-1">
                    Content
                  </Label>
                  <Textarea
                    id="edit-content"
                    value={editedContent}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setEditedContent(e.target.value)}
                    className="min-h-[120px]"
                    placeholder="Edit the action content..."
                  />
                </div>
                <div>
                  <Label htmlFor="edit-note" className="block text-sm font-medium mb-1">
                    Note (optional)
                  </Label>
                  <Textarea
                    id="edit-note"
                    value={editNote}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setEditNote(e.target.value)}
                    className="min-h-[80px]"
                    placeholder="Add a note about your changes..."
                  />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setShowEditDialog(false)}>
                  Cancel
                </Button>
                <Button onClick={handleEdit} disabled={editMutation.isPending}>
                  {editMutation.isPending ? "Saving..." : "Save Changes"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Dialog open={showRejectDialog} onOpenChange={setShowRejectDialog}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1 text-destructive">
                <X className="h-3 w-3" />
                Reject
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <DialogTitle>Reject Action</DialogTitle>
                <DialogDescription>Provide a reason for rejection (required)</DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div>
                  <Label htmlFor="reject-reason" className="block text-sm font-medium mb-1">
                    Rejection Reason
                  </Label>
                  <Textarea
                    id="reject-reason"
                    value={rejectReason}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setRejectReason(e.target.value)}
                    className="min-h-[100px]"
                    placeholder="Explain why you're rejecting this action..."
                    required
                  />
                </div>
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">Common reasons:</p>
                  <div className="flex flex-wrap gap-2">
                    {[
                      "too_long",
                      "too_salesy",
                      "missing_personalization",
                      "wrong_channel",
                      "bad_timing",
                      "wrong_target"
                    ].map((reason) => (
                      <Button
                        key={reason}
                        variant="outline"
                        size="sm"
                        onClick={() => setRejectReason(reason)}
                        className="text-xs"
                      >
                        {reason.replace('_', ' ')}
                      </Button>
                    ))}
                  </div>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setShowRejectDialog(false)}>
                  Cancel
                </Button>
                <Button variant="destructive" onClick={handleReject} disabled={rejectMutation.isPending || !rejectReason.trim()}>
                  {rejectMutation.isPending ? "Rejecting..." : "Reject"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Button 
            onClick={handleApprove} 
            disabled={approveMutation.isPending}
            className="gap-1"
          >
            <Check className="h-3 w-3" />
            {approveMutation.isPending ? "Approving..." : "Approve"}
          </Button>
        </div>
      </CardFooter>
    </Card>
  )
}

function DetailRow({ label, value, icon: Icon }: { label: string; value: string; icon: React.ComponentType<{ className?: string }> }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Icon className="h-3 w-3 text-muted-foreground" />
      <span className="text-muted-foreground">{label}:</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}

function EvidenceItem({ evidence }: { evidence: EvidenceLink }) {
  const icons: Record<string, React.ComponentType<{ className?: string }>> = {
    signal: () => <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>,
    contact: () => <User className="h-3 w-3" />,
    company: () => <Building className="h-3 w-3" />,
    warm_edge: () => <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" /></svg>,
  }

  const Icon = icons[evidence.type] || icons.signal

  return (
    <div className="flex items-start gap-2 p-2 bg-muted/50 rounded-lg">
      <Icon className="h-3 w-3 text-muted-foreground mt-0.5 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-muted-foreground capitalize">{evidence.type.replace('_', ' ')}</p>
        <p className="text-sm truncate">{evidence.description}</p>
        {evidence.payload && (
          <details className="mt-1">
            <summary className="text-xs text-primary cursor-pointer">View payload</summary>
            <pre className="mt-1 text-xs bg-background p-2 rounded overflow-auto max-h-32">
              {JSON.stringify(evidence.payload, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </div>
  )
}

function GuardrailItem({ guardrail }: { guardrail: GuardrailCheck }) {
  return (
    <div className="flex items-center gap-2 p-2 bg-muted/50 rounded-lg">
      <div className={cn(
        "w-2 h-2 rounded-full flex-shrink-0",
        guardrail.passed ? "bg-green-500" : "bg-red-500"
      )} />
      <div className="flex-1">
        <p className="text-sm font-medium">{guardrail.rule}</p>
        {guardrail.details && (
          <p className="text-xs text-muted-foreground">{guardrail.details}</p>
        )}
      </div>
      <Badge variant={guardrail.passed ? "success" : "destructive"} className="text-xs">
        {guardrail.passed ? "Passed" : "Failed"}
      </Badge>
    </div>
  )
}

function LearnedItem({ learned }: { learned: LearningDelta }) {
  const sourceColors: Record<string, string> = {
    outcome: "bg-blue-500",
    feedback: "bg-orange-500",
    warm_graph: "bg-green-500",
  }

  return (
    <div className="flex items-start gap-2 p-2 bg-muted/50 rounded-lg">
      <div className={cn("w-2 h-2 rounded-full flex-shrink-0 mt-1", sourceColors[learned.source])} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium capitalize">{learned.source.replace('_', ' ')}</span>
          <Badge variant="outline" className="text-xs">{learned.field}</Badge>
        </div>
        <p className="text-sm mt-1">{learned.description}</p>
        <p className="text-xs text-muted-foreground">Delta: {learned.delta}</p>
      </div>
    </div>
  )
}