import { useState, useRef, useEffect } from 'react';
import { useProjectStore } from '../store/projectStore.ts';

export function ProjectSwitcher() {
  const { activeProjectId, projects, switchProject, createProject, deleteProject, renameProject } =
    useProjectStore();
  const [open, setOpen] = useState(false);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const dropdownRef = useRef<HTMLDivElement>(null);

  const activeProject = projects.find((p) => p.id === activeProjectId);

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
        setRenameId(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleCreate = () => {
    const name = `Project ${projects.length + 1}`;
    createProject(name);
    setOpen(false);
  };

  const handleDelete = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    deleteProject(id);
    if (projects.length <= 1) setOpen(false);
  };

  const handleStartRename = (id: string, currentName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setRenameId(id);
    setRenameValue(currentName);
  };

  const handleRenameSubmit = (id: string) => {
    const trimmed = renameValue.trim();
    if (trimmed) renameProject(id, trimmed);
    setRenameId(null);
  };

  return (
    <div className="project-switcher" ref={dropdownRef}>
      <button className="toolbar-btn project-switcher-btn" onClick={() => setOpen(!open)}>
        {activeProject?.name || 'Project'} ▾
      </button>

      {open && (
        <div className="project-dropdown">
          <div className="project-dropdown-header">Projects</div>
          <div className="project-dropdown-list">
            {projects.map((p) => (
              <div
                key={p.id}
                className={`project-dropdown-item ${p.id === activeProjectId ? 'active' : ''}`}
                onClick={() => {
                  switchProject(p.id);
                  setOpen(false);
                }}
              >
                {renameId === p.id ? (
                  <input
                    className="project-rename-input"
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRenameSubmit(p.id);
                      if (e.key === 'Escape') setRenameId(null);
                    }}
                    onBlur={() => handleRenameSubmit(p.id)}
                    onClick={(e) => e.stopPropagation()}
                    autoFocus
                  />
                ) : (
                  <span className="project-name">{p.name}</span>
                )}
                <span className="project-actions">
                  <button
                    className="project-action-btn"
                    title="Rename"
                    onClick={(e) => handleStartRename(p.id, p.name, e)}
                  >
                    ✎
                  </button>
                  <button
                    className="project-action-btn project-action-delete"
                    title="Delete"
                    onClick={(e) => handleDelete(p.id, e)}
                  >
                    ×
                  </button>
                </span>
              </div>
            ))}
          </div>
          <button className="project-dropdown-create" onClick={handleCreate}>
            + New Project
          </button>
        </div>
      )}
    </div>
  );
}
