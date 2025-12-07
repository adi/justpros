// Shared post rendering utilities

const defaultPageIcons = {
    company: '/static/default-page-company.svg',
    event: '/static/default-page-event.svg',
    product: '/static/default-page-product.svg',
    community: '/static/default-page-community.svg',
    virtual: '/static/default-page-virtual.svg',
    education: '/static/default-page-education.svg'
};

function getDefaultPageIcon(kind) {
    return defaultPageIcons[kind] || defaultPageIcons.virtual;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'now';
    if (diffMins < 60) return `${diffMins}m`;
    if (diffHours < 24) return `${diffHours}h`;
    if (diffDays < 7) return `${diffDays}d`;

    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// Text emoticon to emoji conversion
const TEXT_EMOJIS = {
    ':)': '😊', ':-)': '😊', ':]': '😊',
    ':D': '😄', ':-D': '😄',
    ';)': '😉', ';-)': '😉',
    ':P': '😛', ':-P': '😛', ':p': '😛', ':-p': '😛',
    ':(': '😞', ':-(': '😞', ':[': '😞',
    ":'(": '😢', ":'-(": '😢',
    ':O': '😮', ':-O': '😮', ':o': '😮', ':-o': '😮',
    'XD': '😆', 'xD': '😆',
    '<3': '❤️',
    ':*': '😘', ':-*': '😘',
    'B)': '😎', 'B-)': '😎',
    ':/': '😕', ':-/': '😕',
    ':S': '😖', ':-S': '😖', ':s': '😖', ':-s': '😖',
    '>:(': '😠', '>:-(': '😠',
    'O:)': '😇', 'O:-)': '😇',
    '>:)': '😈', '>:-)': '😈',
    ':|': '😐', ':-|': '😐',
    '^_^': '😊', '^-^': '😊',
    '-_-': '😑',
    'T_T': '😭', 'T-T': '😭',
    ':3': '😺',
};

function convertTextEmojis(text) {
    // Sort by length (longest first) to match longer patterns before shorter ones
    const sorted = Object.keys(TEXT_EMOJIS).sort((a, b) => b.length - a.length);
    for (const emoticon of sorted) {
        text = text.split(emoticon).join(TEXT_EMOJIS[emoticon]);
    }
    return text;
}

function formatPostContent(content) {
    if (!content) return '';
    // Escape HTML first
    let escaped = escapeHtml(content);
    // Extract URLs before emoticon conversion to protect them
    const urlRegex = /(https?:\/\/[^\s<]+[^\s<.,;:!?\]\)"'])/gi;
    const urls = [];
    escaped = escaped.replace(urlRegex, (match) => {
        urls.push(match);
        return `\x00URL${urls.length - 1}\x00`;
    });
    // Convert text emoticons to emojis (URLs are now protected)
    escaped = convertTextEmojis(escaped);
    // Restore URLs as clickable links (nofollow to prevent reputation transfer)
    escaped = escaped.replace(/\x00URL(\d+)\x00/g, (_, idx) => {
        const url = urls[parseInt(idx)];
        return `<a href="${url}" target="_blank" rel="nofollow noopener noreferrer" class="text-brand-blue hover:underline" onclick="event.stopPropagation()">${url}</a>`;
    });
    // Convert @mentions to links
    escaped = escaped.replace(/@([a-z0-9_]{3,30})\b/g, '<a href="/u/$1" class="text-brand-blue hover:underline" onclick="event.stopPropagation()">@$1</a>');
    return escaped;
}

function renderPostMedia(media) {
    if (!media || media.length === 0) return '';
    const m = media[0];
    if (m.type === 'video') {
        return `<div class="mt-3 -mx-4 bg-black flex justify-center"><video src="${m.url}" controls controlsList="nodownload noplaybackrate" disablePictureInPicture class="max-w-full max-h-[80vh] object-contain" preload="metadata"></video></div>`;
    }
    return `<div class="mt-3 -mx-4 bg-black flex justify-center"><img src="${m.url}" alt="" class="max-w-full max-h-[80vh] object-contain cursor-pointer" onclick="openImageModal('${m.url}', event)"></div>`;
}

let scrollPositionBeforeModal = 0;

function openImageModal(url, event) {
    event.stopPropagation();
    const overlay = document.createElement('div');
    overlay.id = 'image-modal';
    overlay.className = 'fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-[100] cursor-pointer';
    overlay.onclick = () => closeImageModal();
    overlay.innerHTML = `<img src="${url}" alt="" class="max-w-full max-h-full object-contain">`;
    document.body.appendChild(overlay);

    // Lock scroll - iOS Safari requires position fixed approach
    scrollPositionBeforeModal = window.scrollY;
    document.body.style.position = 'fixed';
    document.body.style.top = `-${scrollPositionBeforeModal}px`;
    document.body.style.left = '0';
    document.body.style.right = '0';
    document.body.style.overflow = 'hidden';
}

function closeImageModal() {
    const modal = document.getElementById('image-modal');
    if (modal) {
        modal.remove();

        // Restore scroll
        document.body.style.position = '';
        document.body.style.top = '';
        document.body.style.left = '';
        document.body.style.right = '';
        document.body.style.overflow = '';
        window.scrollTo(0, scrollPositionBeforeModal);
    }
}

// Close image modal on escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeImageModal();
    }
});

// --- Simple Voting System (Reddit-style) ---

const UPVOTE_COLOR = '#16a34a';  // Green for upvotes
const DOWNVOTE_COLOR = '#dc2626';  // Red for downvotes
const DISABLED_COLOR = '#9ca3af';  // Gray for disabled

function renderUpArrow(isActive = false, disabled = false) {
    const color = disabled ? DISABLED_COLOR : (isActive ? UPVOTE_COLOR : 'currentColor');
    const fill = isActive && !disabled ? UPVOTE_COLOR : 'none';
    return `
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="${fill}" stroke="${color}" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7"/>
        </svg>
    `;
}

function renderDownArrow(isActive = false, disabled = false) {
    const color = disabled ? DISABLED_COLOR : (isActive ? DOWNVOTE_COLOR : 'currentColor');
    const fill = isActive && !disabled ? DOWNVOTE_COLOR : 'none';
    return `
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="${fill}" stroke="${color}" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
        </svg>
    `;
}

function renderVoteButtons(itemId, upvotes, downvotes, userVote, canVote, voteType = 'post') {
    const isUpvoted = userVote === 1;
    const isDownvoted = userVote === -1;
    const disabled = !canVote;
    const upvoteColor = isUpvoted && canVote ? `color: ${UPVOTE_COLOR}; font-weight: 600;` : '';
    const downvoteColor = isDownvoted && canVote ? `color: ${DOWNVOTE_COLOR}; font-weight: 600;` : '';
    const textColor = disabled ? `color: ${DISABLED_COLOR};` : '';

    const voteFunc = voteType === 'post' ? 'submitVote' : 'submitFactVote';
    const upClick = canVote ? `onclick="${voteFunc}(${itemId}, ${isUpvoted ? 'null' : '1'}, event)"` : '';
    const downClick = canVote ? `onclick="${voteFunc}(${itemId}, ${isDownvoted ? 'null' : '-1'}, event)"` : '';
    const cursorClass = canVote ? 'cursor-pointer hover:bg-gray-100' : 'cursor-default';

    return `
        <div class="flex items-center border border-gray-200 rounded-full bg-gray-50">
            <button ${upClick} class="flex items-center gap-1 px-2 py-1 rounded-l-full ${cursorClass}" style="${upvoteColor || textColor}">
                ${renderUpArrow(isUpvoted, disabled)}
                <span id="${voteType}-upvotes-${itemId}">${upvotes}</span>
            </button>
            <div class="w-px h-5 bg-gray-200"></div>
            <button ${downClick} class="flex items-center gap-1 px-2 py-1 rounded-r-full ${cursorClass}" style="${downvoteColor || textColor}">
                ${renderDownArrow(isDownvoted, disabled)}
                <span id="${voteType}-downvotes-${itemId}">${downvotes}</span>
            </button>
        </div>
    `;
}

// Legacy functions for backward compatibility (deprecated)
function renderGaugeIcon(level, size = 24) {
    return ''; // No longer used
}

function renderUserVoteBadge(userVote, size = 'normal') {
    return ''; // No longer used
}

function renderScaleIcon(level, size = 24) {
    return ''; // No longer used
}

function renderVotePicker(postId, userVote) {
    return ''; // No longer used - voting is now inline
}

// --- Post Rendering ---

function renderVisibilityIcon(visibility) {
    if (visibility === 'public') {
        return `<svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" title="Public">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
           </svg>`;
    }
    return `<svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" title="Connections only">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
       </svg>`;
}

function renderPostMenu(post, token) {
    const menuItems = [];
    if (token && !post.is_mine) {
        menuItems.push(`<button onclick="reportAbuse(${post.id}); closePostMenu(${post.id})" class="w-full text-left px-4 py-2 text-gray-700 hover:bg-gray-100">Report Abuse</button>`);
    }
    if (post.is_mine) {
        menuItems.push(`<button onclick="showDeleteModal(${post.id}); closePostMenu(${post.id})" class="w-full text-left px-4 py-2 text-red-600 hover:bg-gray-100">Delete</button>`);
    }

    return `
        <div class="relative ml-auto">
            <button onclick="togglePostMenu(${post.id}, event)" class="text-gray-400 hover:text-gray-600 p-1">
                <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z"/>
                </svg>
            </button>
            <div id="post-menu-${post.id}" class="hidden absolute right-0 top-full mt-1 w-36 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-50">
                ${menuItems.join('')}
            </div>
        </div>
    `;
}

function renderPost(post, options = {}) {
    const {
        formatContent = formatPostContent,
        currentUserVotes = {},
        commentsHtml = null,  // If provided, shows comments inline (for single post view)
    } = options;

    const timeStr = formatTime(post.created_at);
    const token = localStorage.getItem('token');
    const canVote = !!token;

    // Track user's vote
    if (post.user_vote !== null && currentUserVotes) {
        currentUserVotes[post.id] = post.user_vote;
    }

    // Vote counts
    const upvotes = post.upvote_count || 0;
    const downvotes = post.downvote_count || 0;

    const visibilityIcon = renderVisibilityIcon(post.visibility || 'public');
    const postMenu = renderPostMenu(post, token);

    // Determine if page post or user post
    const isPagePost = post.page && post.page.handle;
    let headerHtml;

    if (isPagePost) {
        const pageUrl = `/p/${post.page.handle}`;
        const pageIconUrl = post.page.icon_url || defaultPageIcons[post.page.kind] || defaultPageIcons.virtual;
        headerHtml = `
            <a href="${pageUrl}">
                <img src="${pageIconUrl}" alt="" class="w-10 h-10 rounded-lg object-cover bg-gray-200">
            </a>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                    <a href="${pageUrl}" class="font-medium text-base text-gray-900 hover:underline">${escapeHtml(post.page.name)}</a>
                    ${visibilityIcon}
                    <span class="text-gray-400 text-sm">${timeStr}</span>
                    ${postMenu}
                </div>
                <p class="text-gray-800 mt-2 whitespace-pre-wrap break-words">${formatContent(post.content)}</p>
            </div>
        `;
    } else {
        const authorUrl = `/u/${post.author.handle}`;
        const avatarUrl = post.author.avatar_url || '/static/default-avatar.svg';
        headerHtml = `
            <a href="${authorUrl}">
                <img src="${avatarUrl}" alt="" class="w-10 h-10 rounded-full object-cover bg-gray-200">
            </a>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                    <a href="${authorUrl}" class="font-medium text-base text-gray-900 hover:underline">${escapeHtml(post.author.name || post.author.handle)}</a>
                    ${visibilityIcon}
                    <span class="text-gray-400 text-sm">${timeStr}</span>
                    ${postMenu}
                </div>
                <p class="text-gray-800 mt-2 whitespace-pre-wrap break-words">${formatContent(post.content)}</p>
            </div>
        `;
    }

    // Comment button: toggleable in feed view, static count in single post view
    const commentIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
    </svg>`;
    const commentButton = commentsHtml !== null
        ? `<div class="flex items-center gap-1 px-3 py-1 border border-gray-200 rounded-full bg-gray-50 text-gray-600">
               ${commentIcon}
               <span id="comment-count-${post.id}">${post.comment_count || 0}</span>
           </div>`
        : `<button onclick="toggleComments(${post.id})" class="flex items-center gap-1 px-3 py-1 border border-gray-200 rounded-full bg-gray-50 text-gray-600 hover:bg-gray-100 cursor-pointer" id="comment-btn-${post.id}">
               ${commentIcon}
               <span id="comment-count-${post.id}">${post.comment_count || 0}</span>
           </button>`;

    // Comments section: visible with content in single post view, hidden in feed view
    const commentsSection = commentsHtml !== null
        ? `<div id="comments-section-${post.id}" class="border-t border-gray-100">${commentsHtml}</div>`
        : `<div id="comments-section-${post.id}" class="hidden border-t border-gray-100"></div>`;

    // Share button
    const shareIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"/>
    </svg>`;
    const shareButton = `<button onclick="sharePost(${post.id})" class="flex items-center gap-1 px-3 py-1 border border-gray-200 rounded-full bg-gray-50 text-gray-600 hover:bg-gray-100 cursor-pointer">
        ${shareIcon}
    </button>`;

    return `
        <div class="bg-white sm:rounded-lg shadow" data-post-id="${post.id}">
            <div class="p-4">
                <div class="flex items-start gap-3">
                    ${headerHtml}
                </div>
                ${renderPostMedia(post.media)}
                <div class="flex items-center gap-4 mt-3 text-sm">
                    <div id="vote-container-${post.id}">
                        ${renderVoteButtons(post.id, upvotes, downvotes, post.user_vote, canVote, 'post')}
                    </div>
                    ${commentButton}
                    <div class="flex-1"></div>
                    ${shareButton}
                </div>
            </div>
            ${commentsSection}
        </div>
    `;
}

// --- Post Menu Handlers ---

function togglePostMenu(postId, event) {
    event.stopPropagation();
    document.querySelectorAll('[id^="post-menu-"], [id^="comment-menu-"]').forEach(menu => {
        if (menu.id !== `post-menu-${postId}`) {
            menu.classList.add('hidden');
        }
    });
    const menu = document.getElementById(`post-menu-${postId}`);
    if (menu) {
        menu.classList.toggle('hidden');
    }
}

function closePostMenu(postId) {
    const menu = document.getElementById(`post-menu-${postId}`);
    if (menu) {
        menu.classList.add('hidden');
    }
}

function sharePost(postId) {
    const url = `${window.location.origin}/post/${postId}`;
    if (navigator.share) {
        navigator.share({
            title: 'Post on JustPros',
            url: url
        }).catch(() => {});
    } else {
        navigator.clipboard.writeText(url).catch(() => {
            const textarea = document.createElement('textarea');
            textarea.value = url;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
        });
    }
}

// Close menus when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('[id^="comment-menu-"]') && !e.target.closest('[id^="post-menu-"]') && !e.target.closest('button')) {
        document.querySelectorAll('[id^="comment-menu-"], [id^="post-menu-"]').forEach(menu => {
            menu.classList.add('hidden');
        });
    }
});
