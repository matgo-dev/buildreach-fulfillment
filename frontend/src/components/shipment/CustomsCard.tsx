"use client";
import { useState } from "react";
import {
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Popconfirm,
  Space,
  Upload,
} from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  PaperClipOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { useAuthStore } from "@/stores/authStore";
import { Permissions } from "@/config/permission-matrix";
import { colors } from "@/lib/tokens";
import { resolveBizError } from "@/lib/errorMessages";
import {
  shipmentApi,
  type AttachmentPublic,
  type CustomsDeclarationOut,
  type CustomsStatus,
  type ShipmentStatus,
} from "@/lib/shipment";
import { CUSTOMS_STATUS_META } from "@/lib/customsStatus";
import {
  ALLOWED_EXTS,
  MAX_ATTACHMENTS,
  deleteAttachment,
  downloadAttachment,
  formatFileSize,
  uploadAttachment,
  validateFile,
} from "@/lib/attachment";

// 报关卡:发运柜封柜/离港后的报关子资源(录入即已申报,回填放行日 → 已放行)。
// 一柜至多一条活动记录;软删=纠错重录。附件=报关单/放行扫描件,中转上传、鉴权下载。
// customs_status===null(OPEN/CANCELLED 柜)不适用 —— 由详情页据此决定不挂本卡。

/**
 * 附件区(受控列表):抽屉内暂存编辑 + 详情卡就地增删两用。
 * 自身只负责上传/下载/移除交互,不管持久化 —— 由父组件决定(暂存 or 立即 PATCH)。
 */
function CustomsAttachments({
  attachments,
  editable,
  busy,
  onAdd,
  onRemove,
}: {
  attachments: AttachmentPublic[];
  editable: boolean;
  busy?: boolean;
  onAdd: (a: AttachmentPublic) => void;
  onRemove: (id: number) => void;
}) {
  const { message } = App.useApp();
  const [uploading, setUploading] = useState(false);

  async function handleUpload(file: File): Promise<boolean> {
    const err = validateFile(file);
    if (err) {
      message.error(err);
      return false;
    }
    if (attachments.length >= MAX_ATTACHMENTS) {
      message.error(`附件数量超过上限(最多 ${MAX_ATTACHMENTS} 个)`);
      return false;
    }
    setUploading(true);
    try {
      onAdd(await uploadAttachment(file));
    } catch (e) {
      message.error(resolveBizError(e, "上传失败"));
    } finally {
      setUploading(false);
    }
    return false; // 阻断 AntD 默认上传
  }

  async function handleDownload(a: AttachmentPublic) {
    try {
      await downloadAttachment(a.id, a.original_filename);
    } catch (e) {
      message.error(resolveBizError(e, "下载失败"));
    }
  }

  return (
    <div>
      {attachments.length === 0 && !editable ? (
        <span style={{ color: colors.muted }}>无附件</span>
      ) : (
        <Space direction="vertical" size={4} style={{ width: "100%" }}>
          {attachments.map((a) => (
            <div key={a.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <PaperClipOutlined style={{ color: colors.muted }} />
              <Button
                type="link"
                style={{ padding: 0, height: "auto" }}
                onClick={() => handleDownload(a)}
                icon={<DownloadOutlined />}
              >
                {a.original_filename}
              </Button>
              <span style={{ fontSize: 12, color: colors.muted }}>{formatFileSize(a.size_bytes)}</span>
              {editable && (
                <Button
                  type="text"
                  size="small"
                  danger
                  disabled={busy}
                  icon={<DeleteOutlined />}
                  onClick={() => onRemove(a.id)}
                  aria-label="移除附件"
                />
              )}
            </div>
          ))}
        </Space>
      )}
      {editable && attachments.length < MAX_ATTACHMENTS && (
        <Upload
          showUploadList={false}
          accept={ALLOWED_EXTS.join(",")}
          disabled={uploading || busy}
          beforeUpload={(f) => handleUpload(f as File)}
        >
          <Button size="small" icon={<UploadOutlined />} loading={uploading} style={{ marginTop: 8 }}>
            上传附件
          </Button>
        </Upload>
      )}
    </div>
  );
}

export function CustomsCard({
  shipmentId,
  customsStatus,
  declaration,
  onChanged,
}: {
  shipmentId: number;
  // 契约携带柜状态(呈现由 customsStatus 派生口径决定,不在前端另造规则)。
  shipmentStatus: ShipmentStatus;
  customsStatus: CustomsStatus | null;
  declaration: CustomsDeclarationOut | null;
  onChanged: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [modalOpen, setModalOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // Modal 内暂存附件(录入=空;编辑=回填 declaration.attachments 副本,提交时全量替换)。
  const [editAttachments, setEditAttachments] = useState<AttachmentPublic[]>([]);
  // 本次 Modal 会话内新上传的孤儿 id:移除/取消时须回删(deleteAttachment),
  // 否则每次「传了又反悔」都留一个孤儿吃配额;提交成功即转正(清集不删)。
  const [stagedNewIds, setStagedNewIds] = useState<Set<number>>(new Set());

  const canManage = useAuthStore((s) => s.hasPermission(Permissions.SHIPMENT_MANAGE));
  // 放行日不早于申报日(镜像后端守卫)。
  const declaredAt = Form.useWatch("declared_at", form) as dayjs.Dayjs | undefined;
  const releasedDisabled = (d: dayjs.Dayjs) => !!declaredAt && d.isBefore(declaredAt, "day");

  // 详情页已按 customs_status!==null 才挂本卡;此处防御性兜底。
  if (customsStatus === null) return null;

  function openCreate() {
    form.resetFields();
    form.setFieldsValue({ declared_at: dayjs() });
    setEditAttachments([]);
    setStagedNewIds(new Set());
    setModalOpen(true);
  }

  function openEdit() {
    if (!declaration) return;
    form.setFieldsValue({
      declaration_no: declaration.declaration_no,
      declared_at: dayjs(declaration.declared_at),
      released_at: declaration.released_at ? dayjs(declaration.released_at) : undefined,
      declarant: declaration.declarant ?? undefined,
      customs_office: declaration.customs_office ?? undefined,
      note: declaration.note ?? undefined,
    });
    setEditAttachments([...declaration.attachments]);
    setStagedNewIds(new Set());
    setModalOpen(true);
  }

  // 取消/关闭 Modal:回删本会话新上传、仍暂存中的孤儿(best-effort,不阻塞关窗)。
  function closeModalDiscard() {
    stagedNewIds.forEach((id) => {
      deleteAttachment(id).catch(() => {});
    });
    setStagedNewIds(new Set());
    setModalOpen(false);
  }

  async function onSubmit() {
    const v = await form.validateFields().catch(() => null);
    if (!v) return;
    const attachment_ids = editAttachments.map((a) => a.id);
    const shared = {
      declaration_no: (v.declaration_no as string).trim(),
      declared_at: (v.declared_at as dayjs.Dayjs).format("YYYY-MM-DD"),
      released_at: v.released_at ? (v.released_at as dayjs.Dayjs).format("YYYY-MM-DD") : null,
      declarant: (v.declarant as string | undefined)?.trim() || null,
      customs_office: (v.customs_office as string | undefined)?.trim() || null,
      note: (v.note as string | undefined)?.trim() || null,
      attachment_ids,
    };
    setBusy(true);
    try {
      if (!declaration) {
        await shipmentApi.createCustoms(shipmentId, shared);
        message.success("已录入报关");
      } else {
        await shipmentApi.updateCustoms(shipmentId, declaration.id, {
          ...shared,
          expected_updated_at: declaration.updated_at,
        });
        message.success("已更新报关");
      }
      setStagedNewIds(new Set()); // 提交成功:暂存孤儿已转正(挂上报关),不再回删
      setModalOpen(false);
      onChanged();
    } catch (e) {
      // 42012 柜状态不可报关 / 42013 已有记录 / 42015 冲突 / 421xx 附件(errorMessages 映射中文)。
      // 提交失败 Modal 不关,暂存集保留,后续取消时统一回删。
      message.error(resolveBizError(e, "保存失败"));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!declaration) return;
    setBusy(true);
    try {
      await shipmentApi.deleteCustoms(shipmentId, declaration.id);
      message.success("已删除报关记录");
      onChanged();
    } catch (e) {
      message.error(resolveBizError(e, "删除失败"));
    } finally {
      setBusy(false);
    }
  }

  // 详情卡内附件就地增删:立即 PATCH 全量替换(携乐观锁基线)。
  async function persistAttachments(nextIds: number[], ok: string) {
    if (!declaration) return;
    setBusy(true);
    try {
      await shipmentApi.updateCustoms(shipmentId, declaration.id, {
        expected_updated_at: declaration.updated_at,
        attachment_ids: nextIds,
      });
      message.success(ok);
      onChanged();
    } catch (e) {
      message.error(resolveBizError(e, "保存失败"));
    } finally {
      setBusy(false);
    }
  }

  const body =
    customsStatus === "NONE" || !declaration ? (
      <Empty description="尚未录入报关">
        <Can perm={Permissions.SHIPMENT_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            录入报关
          </Button>
        </Can>
      </Empty>
    ) : (
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="报关单号">{declaration.declaration_no}</Descriptions.Item>
        <Descriptions.Item label="申报日期">{declaration.declared_at}</Descriptions.Item>
        <Descriptions.Item label="放行日期">{declaration.released_at || "—"}</Descriptions.Item>
        <Descriptions.Item label="申报单位">{declaration.declarant || "—"}</Descriptions.Item>
        <Descriptions.Item label="口岸">{declaration.customs_office || "—"}</Descriptions.Item>
        <Descriptions.Item label="备注">{declaration.note || "—"}</Descriptions.Item>
        <Descriptions.Item label="附件" span={2}>
          <CustomsAttachments
            attachments={declaration.attachments}
            editable={canManage}
            busy={busy}
            onAdd={(a) =>
              persistAttachments([...declaration.attachments.map((x) => x.id), a.id], "已添加附件")
            }
            onRemove={(id) =>
              persistAttachments(
                declaration.attachments.filter((x) => x.id !== id).map((x) => x.id),
                "已移除附件",
              )
            }
          />
        </Descriptions.Item>
      </Descriptions>
    );

  return (
    <Card
      title={
        <Space size={8}>
          <span>报关</span>
          {declaration ? (
            <StatusTag meta={CUSTOMS_STATUS_META} value={declaration.status} />
          ) : null}
        </Space>
      }
      extra={
        declaration ? (
          <Can perm={Permissions.SHIPMENT_MANAGE}>
            <Space>
              <Button icon={<EditOutlined />} onClick={openEdit}>
                编辑
              </Button>
              <Popconfirm
                title="删除报关记录?"
                description="软删除,用于纠错重录;附件一并归档。删除后可重新录入。"
                okButtonProps={{ danger: true }}
                onConfirm={onDelete}
              >
                <Button danger disabled={busy}>
                  删除重录
                </Button>
              </Popconfirm>
            </Space>
          </Can>
        ) : null
      }
    >
      {body}

      <Drawer
        title={declaration ? "编辑报关" : "录入报关"}
        open={modalOpen}
        size="min(560px, 92vw)"
        destroyOnHidden
        onClose={closeModalDiscard}
        footer={
          <Space style={{ width: "100%", justifyContent: "flex-end" }}>
            <Button onClick={closeModalDiscard} disabled={busy}>
              取消
            </Button>
            <Button type="primary" loading={busy} onClick={onSubmit}>
              保存
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="declaration_no"
            label="报关单号"
            rules={[{ required: true, message: "请填写报关单号" }]}
          >
            <Input placeholder="必填" maxLength={32} />
          </Form.Item>
          <Form.Item
            name="declared_at"
            label="申报日期"
            rules={[{ required: true, message: "请填写申报日期" }]}
          >
            <DatePicker style={{ width: "100%" }} allowClear={false} />
          </Form.Item>
          <Form.Item name="released_at" label="放行日期" help="放行后回填;不早于申报日">
            <DatePicker style={{ width: "100%" }} disabledDate={releasedDisabled} />
          </Form.Item>
          <Form.Item name="declarant" label="申报单位">
            <Input placeholder="选填" maxLength={100} />
          </Form.Item>
          <Form.Item name="customs_office" label="口岸">
            <Input placeholder="选填" maxLength={100} />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} placeholder="选填" maxLength={500} />
          </Form.Item>
          <Form.Item label="附件" help={`报关单 / 放行扫描件,最多 ${MAX_ATTACHMENTS} 个`}>
            <CustomsAttachments
              attachments={editAttachments}
              editable
              busy={busy}
              onAdd={(a) => {
                setEditAttachments((s) => [...s, a]);
                setStagedNewIds((s) => new Set(s).add(a.id));
              }}
              onRemove={(id) => {
                setEditAttachments((s) => s.filter((x) => x.id !== id));
                // 本会话新传的 → 真删孤儿;原有已挂的 → 仅移出暂存(提交时全量替换软删)。
                if (stagedNewIds.has(id)) {
                  deleteAttachment(id).catch(() => {});
                  setStagedNewIds((s) => {
                    const next = new Set(s);
                    next.delete(id);
                    return next;
                  });
                }
              }}
            />
          </Form.Item>
        </Form>
      </Drawer>
    </Card>
  );
}
