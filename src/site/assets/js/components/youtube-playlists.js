/* ==========================================================================
   WantToKnow.info YouTube Playlist Component
   ========================================================================== */

let playlistDataPromise = null;


function loadPlaylistData() {

  if (!playlistDataPromise) {

    playlistDataPromise =
      fetch(
        "/data/youtube-playlists.json"
      )
      .then((response) => {

        if (!response.ok) {
          throw new Error(
            `Unable to load playlists: ${response.status}`
          );
        }

        return response.json();
      })
      .catch((error) => {

        playlistDataPromise = null;

        throw error;
      });
  }

  return playlistDataPromise;
}


function makeElement(
  tagName,
  className = ""
) {

  const element =
    document.createElement(
      tagName
    );

  if (className) {
    element.className =
      className;
  }

  return element;
}


/* ==========================================================================
   Video modal
   ========================================================================== */

const modal =
  document.getElementById(
    "youtube-video-modal"
  );

const modalTitle =
  document.getElementById(
    "youtube-video-modal-title"
  );

const playerContainer =
  document.getElementById(
    "youtube-video-player"
  );

const closeButton =
  modal?.querySelector(
    ".youtube-video-modal-close"
  );


function openYouTubeVideo(video) {

  if (
    !modal ||
    !playerContainer
  ) {
    return;
  }


  modalTitle.textContent =
    video.title || "Video";


  const iframe =
    document.createElement(
      "iframe"
    );

  /*
   * Privacy-enhanced YouTube embed.
   *
   * The iframe does not exist until the
   * visitor explicitly selects a video.
   */
  iframe.src =
    "https://www.youtube-nocookie.com/embed/" +
    encodeURIComponent(
      video.video_id
    ) +
    "?autoplay=1&playsinline=1";

  iframe.title =
    video.title || "YouTube video";

  iframe.allow =
    "accelerometer; autoplay; encrypted-media; " +
    "gyroscope; picture-in-picture; web-share";

  iframe.allowFullscreen = true;

  iframe.setAttribute(
    "referrerpolicy",
    "strict-origin-when-cross-origin"
  );


  playerContainer.replaceChildren(
    iframe
  );


  modal.showModal();
}


function closeYouTubeVideo() {

  if (!modal) {
    return;
  }

  modal.close();
}


closeButton?.addEventListener(
  "click",
  closeYouTubeVideo
);


/*
 * Clicking the dark backdrop closes
 * the modal.
 */
modal?.addEventListener(
  "click",
  (event) => {

    if (event.target === modal) {
      closeYouTubeVideo();
    }
  }
);


/*
 * Removing the iframe immediately stops
 * playback and unloads the YouTube player.
 */
modal?.addEventListener(
  "close",
  () => {

    playerContainer?.replaceChildren();

    if (modalTitle) {
      modalTitle.textContent =
        "Video";
    }
  }
);


/* ==========================================================================
   Playlist component
   ========================================================================== */

class WtkYouTubePlaylist
  extends HTMLElement {

  connectedCallback() {

    if (this.dataset.mounted) {
      return;
    }

    this.dataset.mounted =
      "true";

    this.renderLoading();

    this.load();
  }


  get playlistKey() {

    return (
      this.getAttribute(
        "playlist"
      ) || ""
    );
  }


  get limit() {

    const value =
      Number.parseInt(
        this.getAttribute(
          "limit"
        ) || "8",
        10
      );

    return (
      Number.isFinite(value) &&
      value > 0
    )
      ? value
      : 8;
  }


  renderLoading() {

    const panel =
      makeElement(
        "section",
        "youtube-playlist-panel"
      );

    const loading =
      makeElement(
        "p",
        "youtube-playlist-loading"
      );

    loading.textContent =
      "Loading videos…";

    panel.append(
      loading
    );

    this.replaceChildren(
      panel
    );
  }


  async load() {

    try {

      const data =
        await loadPlaylistData();

      const playlist =
        data?.playlists?.[
          this.playlistKey
        ];


      if (!playlist) {

        throw new Error(
          `Unknown playlist: ${this.playlistKey}`
        );
      }


      this.renderPlaylist(
        playlist
      );

    } catch (error) {

      console.error(
        "[wtk-youtube-playlist]",
        error
      );

      this.renderError();
    }
  }


  renderPlaylist(playlist) {

    const panel =
      makeElement(
        "section",
        "youtube-playlist-panel"
      );


    /* Header */

    const header =
      makeElement(
        "header",
        "youtube-playlist-header"
      );


    const headingCopy =
      makeElement(
        "div",
        "youtube-playlist-heading-copy"
      );


    const eyebrow =
      makeElement(
        "p",
        "eyebrow"
      );

    eyebrow.textContent =
      "Youtube Channel";


    const heading =
      document.createElement(
        "h3"
      );

    heading.textContent =
      playlist.title;


    headingCopy.append(
      eyebrow,
      heading
    );


    const playlistLink =
      makeElement(
        "a",
        "youtube-playlist-link"
      );

    playlistLink.href =
      "https://www.youtube.com/playlist?list=" +
      encodeURIComponent(
        playlist.playlist_id
      );

    playlistLink.target =
      "_blank";

    playlistLink.rel =
      "noopener noreferrer";

    playlistLink.textContent =
      "View playlist ↗";


    header.append(
      headingCopy,
      playlistLink
    );


    /* Video list */

    const list =
      makeElement(
        "div",
        "youtube-playlist-videos"
      );


    const videos =
      playlist.videos.slice(
        0,
        this.limit
      );


    videos.forEach(
      (video, index) => {

        list.append(
          this.createVideoCard(
            video,
            index
          )
        );
      }
    );


    panel.append(
      header,
      list
    );


    this.replaceChildren(
      panel
    );
  }


  createVideoCard(
    video,
    index
  ) {

    const button =
      makeElement(
        "button",
        "youtube-video-card"
      );

    button.type =
      "button";


    /* Thumbnail */

    const thumb =
      makeElement(
        "span",
        "youtube-video-thumb"
      );


    const image =
      document.createElement(
        "img"
      );

    image.src =
      video.thumbnail;

    image.alt = "";

    image.loading =
      "lazy";

    image.decoding =
      "async";


    const play =
      makeElement(
        "span",
        "youtube-video-play"
      );

    play.setAttribute(
      "aria-hidden",
      "true"
    );

    play.innerHTML = `
      <svg viewBox="0 0 40 40">
        <circle
          cx="20"
          cy="20"
          r="18"
        />
        <path
          d="M16 12.8 28 20 16 27.2Z"
        />
      </svg>
    `;


    thumb.append(
      image,
      play
    );


    /* Copy */

    const copy =
      makeElement(
        "span",
        "youtube-video-copy"
      );


    const number =
      makeElement(
        "span",
        "youtube-video-number"
      );

    number.textContent =
      String(
        index + 1
      ).padStart(
        2,
        "0"
      );


    const title =
      makeElement(
        "strong",
        "youtube-video-title"
      );

    title.textContent =
      video.title;


    copy.append(
      number,
      title
    );


    button.append(
      thumb,
      copy
    );


    button.addEventListener(
      "click",
      () => {

        openYouTubeVideo(
          video
        );
      }
    );


    return button;
  }


  renderError() {

    const panel =
      makeElement(
        "section",
        "youtube-playlist-panel"
      );

    const message =
      makeElement(
        "p",
        "youtube-playlist-error"
      );

    message.textContent =
      "Videos are temporarily unavailable.";

    panel.append(
      message
    );

    this.replaceChildren(
      panel
    );
  }
}


if (
  !customElements.get(
    "wtk-youtube-playlist"
  )
) {

  customElements.define(
    "wtk-youtube-playlist",
    WtkYouTubePlaylist
  );
}