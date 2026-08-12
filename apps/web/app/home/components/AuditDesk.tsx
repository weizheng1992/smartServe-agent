import type React from "react";
import type { PendingApprovalRecord } from "types";
import type { UserSession } from "../hooks/types";
import { ApprovalDetailView } from "./audit/ApprovalDetailView";
import {
  ApprovalFilterHeader,
  type AuditFilterType,
} from "./audit/ApprovalFilterHeader";
import { ApprovalList } from "./audit/ApprovalList";

interface AuditDeskProps {
  currentUser: UserSession | null;
  allApprovals: PendingApprovalRecord[];
  selectedApprovalId: string | null;
  setSelectedApprovalId: (id: string | null) => void;
  auditFilter: AuditFilterType;
  setAuditFilter: (filter: AuditFilterType) => void;
  rejectionInput: string;
  setRejectionReason: (val: string) => void;
  isSubmitting: boolean;
  handleApprovalAction: (
    approvalId: string,
    action: "approve" | "reject",
  ) => Promise<void>;
  setActiveTab: (tab: "CHAT_DESK" | "AUDIT_DESK") => void;
}

export function AuditDesk({
  allApprovals,
  selectedApprovalId,
  setSelectedApprovalId,
  auditFilter,
  setAuditFilter,
  rejectionInput,
  setRejectionReason,
  isSubmitting,
  handleApprovalAction,
  setActiveTab,
}: AuditDeskProps) {
  const selectedApproval = allApprovals.find(
    (a) => a.id === selectedApprovalId,
  );

  return (
    <div className="flex-1 flex flex-col bg-slate-950 p-6 overflow-hidden">
      <ApprovalFilterHeader
        allApprovals={allApprovals}
        auditFilter={auditFilter}
        setAuditFilter={setAuditFilter}
        setSelectedApprovalId={setSelectedApprovalId}
      />

      <div className="flex-1 flex gap-6 overflow-hidden pt-6">
        <ApprovalList
          allApprovals={allApprovals}
          auditFilter={auditFilter}
          selectedApprovalId={selectedApprovalId}
          setSelectedApprovalId={setSelectedApprovalId}
        />

        <ApprovalDetailView
          selectedApproval={selectedApproval}
          rejectionInput={rejectionInput}
          setRejectionReason={setRejectionReason}
          isSubmitting={isSubmitting}
          handleApprovalAction={handleApprovalAction}
          setActiveTab={setActiveTab}
        />
      </div>
    </div>
  );
}
